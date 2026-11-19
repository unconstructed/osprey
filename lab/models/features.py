"""Point-in-time features for the prediction models.

Every feature at bar t is a function of a fixed trailing window of bars ending at t (``BARS_NEEDED``
gives each window), never of anything after t. Fixed finite windows (including the EWMA, which uses
only the last ``EWMA_WINDOW`` log returns) make each value reproducible live from a short buffer:
:class:`lab.models.online.FeatureBuffer` holds the last ``WARMUP`` bars and returns exactly the same
numbers as :func:`compute_features` on the full history.

Conventions
- Returns are log returns ``ln(close[t] / close[t-k])``; volatilities are per bar (not annualised),
  sample standard deviations (``ddof=1``) of log returns.
- A row is either complete or entirely NaN: rows before ``WARMUP - 1`` (the first bar with every
  window filled) are NaN in every column.
- All features are invariant to rescaling prices (open, high, low, close by one factor) and to
  rescaling volume.

Bit-exact reproducibility (batch vs. live) needs every window's value to depend only on that window's
numbers, so every helper here follows two rules:
- Window statistics are computed per window from its own values (:func:`rolling_windows` plus
  :func:`row_sum`, which adds left to right), never with pandas ``rolling``. pandas keeps running
  sums whose round-off carries over from every earlier bar: on the test market a 101-bar buffer and
  the full history disagree in the last bits on a third to three quarters of the bars.
- Logs are taken element by element with the scalar ``math.log``: one code path for every array
  length, so a value never depends on numpy's SIMD dispatch (vector body vs. remainder loop). numpy's
  ``np.log`` and ``math.log`` differ in the last bit on about 4% of daily returns, so the batch and the
  live code must use the same one; position-dependent ``np.log`` results were not observed on
  numpy 2.5 (AVX-512), and ``math.log`` makes the question moot.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from lab.runner.interface import validate_bars

FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_5",
    "ret_20",
    "ret_60",
    "vol_10",
    "vol_20",
    "vol_60",
    "ewma_vol_20",
    "park_vol_20",
    "ma_dist_20",
    "ma_dist_100",
    "drawdown_60",
    "eff_ratio_20",
    "volume_z_20",
    "vol_ratio_10_60",
)

EWMA_SPAN = 20
EWMA_WINDOW = 100  # log returns in the finite EWMA window

# Bars each feature at t reads: bars t - n + 1 .. t. (k-bar returns need k + 1 closes; a volatility of
# w log returns needs w + 1 closes.)
BARS_NEEDED: Mapping[str, int] = {
    "ret_1": 2,
    "ret_5": 6,
    "ret_20": 21,
    "ret_60": 61,
    "vol_10": 11,
    "vol_20": 21,
    "vol_60": 61,
    "ewma_vol_20": EWMA_WINDOW + 1,
    "park_vol_20": 20,
    "ma_dist_20": 20,
    "ma_dist_100": 100,
    "drawdown_60": 60,
    "eff_ratio_20": 21,
    "volume_z_20": 20,
    "vol_ratio_10_60": 61,
}

# Bars needed before every feature is defined: row WARMUP - 1 is the first complete row, and
# FeatureBuffer.latest() returns values from the WARMUP-th bar on.
WARMUP = max(BARS_NEEDED.values())

RANK_SUFFIX = "_xs_rank"

# Relative flatness: a spread this small next to the size of the values is round-off, not variation
# (same rule as lab.validation.stats, TESTING 5.2A). Used where a spread is a denominator.
_REL_TOL = 1e-9
_PARKINSON_DENOM = 4.0 * math.log(2.0)


# ----------------------------------------------------------------------------- shared window helpers


def log_array(x: np.ndarray) -> np.ndarray:
    """Natural log of each element with the scalar ``math.log`` (same code path however long ``x`` is)."""
    return np.fromiter(map(math.log, np.asarray(x, dtype=float).tolist()), dtype=float, count=len(x))


def rolling_windows(x: np.ndarray, w: int) -> np.ndarray:
    """Read-only ``(len(x) - w + 1, w)`` view: row i holds ``x[i : i + w]``."""
    return np.lib.stride_tricks.sliding_window_view(x, w)


def row_sum(win: np.ndarray) -> np.ndarray:
    """Sum of each row of a 2-D array, adding the columns left to right (fixed order, see module doc)."""
    total = win[:, 0].copy()
    for j in range(1, win.shape[1]):
        total += win[:, j]
    return total


def row_std(win: np.ndarray) -> np.ndarray:
    """Sample standard deviation (``ddof=1``) of each row; rows need at least 2 values."""
    w = win.shape[1]
    mean = row_sum(win) / w
    dev = win - mean[:, None]
    return np.sqrt(row_sum(dev * dev) / (w - 1))


def efficiency_ratio(net: np.ndarray, path: np.ndarray) -> np.ndarray:
    """Kaufman efficiency ratio ``|net move| / sum of |moves|``, in [0, 1].

    A window with no movement at all (``path == 0``) is not trending: 0. Clipped at 1 because round-off
    in the sum can put a perfectly straight path a hair above it.
    """
    moved = path > 0
    ratio = np.abs(net) / np.where(moved, path, 1.0)
    return np.where(moved, np.minimum(ratio, 1.0), 0.0)


def ewma_weights(span: int, window: int) -> np.ndarray:
    """EWMA weights for a window ordered oldest to newest: ``lam ** (window - 1 - j)``, ``lam = 1 - 2/(span+1)``."""
    lam = 1.0 - 2.0 / (span + 1.0)
    return np.array([lam ** (window - 1 - j) for j in range(window)])


def ewma_vol_rows(lr_win: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """sqrt of the weight-normalised EWMA of squared log returns, one value per window row.

    Not demeaned (RiskMetrics style). ``weights`` comes from :func:`ewma_weights`.
    """
    sq = lr_win * lr_win
    acc = weights[0] * sq[:, 0]
    for j in range(1, len(weights)):
        acc += weights[j] * sq[:, j]
    return np.sqrt(acc / float(np.sum(weights)))


def log_returns(close: np.ndarray) -> np.ndarray:
    """One log return per bar, ``lr[t] = ln(close[t] / close[t-1])``; ``lr[0]`` is NaN."""
    lr = np.full(len(close), np.nan)
    lr[1:] = log_array(close[1:] / close[:-1])
    return lr


def bar_arrays(bars: pd.DataFrame) -> tuple[np.ndarray, ...]:
    """Validated ``open, high, low, close, volume`` as contiguous float64 arrays."""
    validate_bars(bars)
    return tuple(
        np.ascontiguousarray(bars[col].to_numpy(dtype=float))
        for col in ("open", "high", "low", "close", "volume")
    )


# ----------------------------------------------------------------------------- features


def feature_matrix(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray
) -> np.ndarray:
    """``(n, len(FEATURES))`` feature array from bar arrays; rows before ``WARMUP - 1`` are NaN.

    The inputs must already be valid bars (see :func:`lab.runner.interface.validate_bars`). Row t uses
    only bars ``t - WARMUP + 1 .. t``. No feature reads the open; it is in the signature so callers
    always pass whole bars.
    """
    n = len(close)
    out = np.full((n, len(FEATURES)), np.nan)
    if n < WARMUP:
        return out
    first = WARMUP - 1  # first complete row

    def tail(x: np.ndarray, w: int) -> np.ndarray:
        # windows of length w ending at rows first .. n-1
        return rolling_windows(x, w)[first - w + 1 :]

    c_now = close[first:]
    lr = log_returns(close)
    cols: dict[str, np.ndarray] = {}
    for k in (1, 5, 20, 60):
        cols[f"ret_{k}"] = log_array(c_now / close[first - k : n - k])
    for w in (10, 20, 60):
        cols[f"vol_{w}"] = row_std(tail(lr, w))
    cols["ewma_vol_20"] = ewma_vol_rows(tail(lr, EWMA_WINDOW), ewma_weights(EWMA_SPAN, EWMA_WINDOW))

    hl = log_array(high / low)
    cols["park_vol_20"] = np.sqrt(row_sum(tail(hl * hl, 20)) / (20 * _PARKINSON_DENOM))

    for w in (20, 100):
        cols[f"ma_dist_{w}"] = c_now / (row_sum(tail(close, w)) / w) - 1.0
    cols["drawdown_60"] = c_now / tail(close, 60).max(axis=1) - 1.0

    moves = np.full(n, np.nan)
    moves[1:] = np.abs(close[1:] - close[:-1])
    cols["eff_ratio_20"] = efficiency_ratio(c_now - close[first - 20 : n - 20], row_sum(tail(moves, 20)))

    vwin = tail(volume, 20)
    v_mean = row_sum(vwin) / 20
    v_dev = vwin - v_mean[:, None]
    v_sd = np.sqrt(row_sum(v_dev * v_dev) / 19)
    v_flat = v_sd <= _REL_TOL * vwin.max(axis=1)  # constant (or all-zero) volume: no surprise
    cols["volume_z_20"] = np.where(v_flat, 0.0, (volume[first:] - v_mean) / np.where(v_flat, 1.0, v_sd))

    lr_scale = np.abs(tail(lr, 60)).max(axis=1)
    vol_flat = cols["vol_60"] <= _REL_TOL * lr_scale  # no variation over 60 bars: ratio is 0/0, call it 1
    cols["vol_ratio_10_60"] = np.where(
        vol_flat, 1.0, cols["vol_10"] / np.where(vol_flat, 1.0, cols["vol_60"])
    )

    out[first:] = np.column_stack([cols[name] for name in FEATURES])
    return out


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """The ``FEATURES`` columns for every bar, point in time.

    ``bars`` follows the bar conventions (validated). The result has ``bars.index`` and float64
    columns in ``FEATURES`` order; rows before ``WARMUP - 1`` are NaN.
    """
    arrays = bar_arrays(bars)
    return pd.DataFrame(feature_matrix(*arrays), index=bars.index, columns=list(FEATURES))


def cross_sectional_ranks(
    features_by_asset: Mapping[str, pd.DataFrame], cols: Sequence[str] | None = None
) -> dict[str, pd.DataFrame]:
    """Percentile rank of each feature across assets, date by date.

    For each asset, a DataFrame on that asset's index with one column ``<col>_xs_rank`` per ranked
    column (``cols`` defaults to ``FEATURES``). Ranks follow ``pandas.DataFrame.rank(axis=1, pct=True)``:
    rank / number of assets with a value that date, ties averaged, so the highest value gets 1.0 and
    with two assets the lower gets 0.5. A NaN feature gets a NaN rank and is left out of that date's
    count. Only same-date values are compared, so ranks are as point-in-time as the features.
    """
    if not features_by_asset:
        raise ValueError("features_by_asset is empty")
    cols = list(FEATURES if cols is None else cols)
    for asset, frame in features_by_asset.items():
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise ValueError(f"features for {asset!r} are missing columns: {missing}")
    assets = list(features_by_asset)
    ranked: dict[str, dict[str, pd.Series]] = {a: {} for a in assets}
    for col in cols:
        table = pd.DataFrame({a: features_by_asset[a][col] for a in assets})
        ranks = table.rank(axis=1, pct=True, method="average")
        for a in assets:
            ranked[a][f"{col}{RANK_SUFFIX}"] = ranks[a].reindex(features_by_asset[a].index)
    return {a: pd.DataFrame(ranked[a], index=features_by_asset[a].index) for a in assets}
