"""Labels (prediction targets): what happens AFTER bar t, for training and evaluation only.

A label at bar t looks at bars t+1 .. t+horizon (closes t .. t+horizon), so it is unknown at the
close of t. Labels must never be used as features: every label is named with ``LABEL_PREFIX``
(``"y_"``), and no feature name starts with it. The last ``horizon`` rows have no complete future
window and are NaN.

Conventions: log returns for volatility (per bar, sample standard deviation ``ddof=1``, matching the
volatility features and baselines); simple returns for ``forward_return``.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from lab.models.features import efficiency_ratio, log_array, rolling_windows, row_std, row_sum
from lab.runner.interface import validate_bars

LABEL_PREFIX = "y_"


def _check_horizon(horizon: int, minimum: int) -> None:
    if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)) or horizon < minimum:
        raise ValueError(f"horizon must be an int >= {minimum}, got {horizon!r}")


def _close(bars: pd.DataFrame) -> np.ndarray:
    validate_bars(bars)
    return bars["close"].to_numpy(dtype=float)


def forward_vol(bars: pd.DataFrame, horizon: int) -> pd.Series:
    """Realised volatility over the next ``horizon`` bars: std (ddof=1) of log returns of bars t+1..t+h.

    Named ``y_vol_<horizon>``. ``horizon >= 2`` (one return has no sample spread).
    """
    _check_horizon(horizon, 2)
    c = _close(bars)
    n = len(c)
    out = np.full(n, np.nan)
    if n > horizon:
        lr = log_array(c[1:] / c[:-1])  # lr[j] is the return of bar j + 1
        out[: n - horizon] = row_std(rolling_windows(lr, horizon))
    return pd.Series(out, index=bars.index, name=f"{LABEL_PREFIX}vol_{horizon}")


def forward_return(bars: pd.DataFrame, horizon: int) -> pd.Series:
    """Simple return from close t to close t+h: ``close[t+h] / close[t] - 1``. Named ``y_ret_<horizon>``."""
    _check_horizon(horizon, 1)
    c = _close(bars)
    n = len(c)
    out = np.full(n, np.nan)
    if n > horizon:
        out[: n - horizon] = c[horizon:] / c[: n - horizon] - 1.0
    return pd.Series(out, index=bars.index, name=f"{LABEL_PREFIX}ret_{horizon}")


def forward_regime(bars: pd.DataFrame, horizon: int, threshold: float = 0.3) -> pd.Series:
    """1.0 (trend) if the efficiency ratio of closes t..t+h is ``>= threshold``, else 0.0 (sideways).

    Efficiency ratio = ``|close[t+h] - close[t]| / sum |close[i] - close[i-1]|`` over i = t+1..t+h
    (0 when the price does not move). Named ``y_regime_<horizon>``; ``0 <= threshold <= 1``.
    """
    _check_horizon(horizon, 1)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold!r}")
    c = _close(bars)
    n = len(c)
    out = np.full(n, np.nan)
    if n > horizon:
        net = c[horizon:] - c[: n - horizon]
        path = row_sum(rolling_windows(np.abs(np.diff(c)), horizon))
        out[: n - horizon] = (efficiency_ratio(net, path) >= threshold).astype(float)
    return pd.Series(out, index=bars.index, name=f"{LABEL_PREFIX}regime_{horizon}")


def cross_sectional_forward_rank(
    bars_by_asset: Mapping[str, pd.DataFrame], horizon: int
) -> dict[str, pd.Series]:
    """Percentile rank of each asset's ``forward_return`` across assets, date by date.

    Same rank convention as :func:`lab.models.features.cross_sectional_ranks` (``pct=True``, ties
    averaged, the best asset gets 1.0, NaN left out). Named ``y_xs_rank_<horizon>``; one Series per
    asset on that asset's index.
    """
    if not bars_by_asset:
        raise ValueError("bars_by_asset is empty")
    fwd = {asset: forward_return(bars, horizon) for asset, bars in bars_by_asset.items()}
    ranks = pd.DataFrame(fwd).rank(axis=1, pct=True, method="average")
    name = f"{LABEL_PREFIX}xs_rank_{horizon}"
    return {asset: ranks[asset].reindex(bars.index).rename(name) for asset, bars in bars_by_asset.items()}
