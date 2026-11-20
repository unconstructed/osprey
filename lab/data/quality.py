"""Data quality checks for normalised bars (UTC close-time index, OHLCV float64).

Nothing here changes data. Every function returns plain JSON-ready dicts for ``SNAPSHOT.json`` and the
quality report; the build decides what to drop and records it. Gaps are never filled.

- :func:`check_series`: rows and span, bars off the interval grid, duplicates and order, missing bars and the
  longest gaps, bad ticks that survived loading (non-positive or OHLC-inconsistent), zero-volume bars,
  extreme moves (``|log r| > k`` times the rolling sigma of the PREVIOUS bars' log returns) and extreme
  wicks (high or low that far beyond the body), and stale closes (runs of unchanged closes).
- :func:`compare_intervals`: daily bars against the same source's hourly bars aggregated to days. On a
  clean source the OHLC agree exactly; this catches time-zone and alignment errors.
- :func:`cross_check`: the same day's close from several sources must agree within a tolerance; every
  outlier is listed with its values.
- :func:`lag_alignment`: two sources agree best with no time shift (catches time-zone and labelling errors).
- :func:`window_coverage`: how much of a split window (e.g. train) a series covers.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations

import numpy as np
import pandas as pd

from lab.config import in_window
from lab.data.loaders import resample

INTERVALS = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1)}
PRICES = ("open", "high", "low", "close")


def step_of(interval: str) -> pd.Timedelta:
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {sorted(INTERVALS)}, got {interval!r}")
    return INTERVALS[interval]


def iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).isoformat()


def _ns(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(index.as_unit("ns").asi8, dtype=np.int64)


def find_gaps(index: pd.DatetimeIndex, step: pd.Timedelta) -> list[dict]:
    """Every run of missing bars between consecutive bars of a sorted close-time ``index``.

    A gap is ``{"after": last close before it, "before": first close after it, "missing": bars absent}``;
    ``missing`` is the number of whole grid steps between the two closes minus one (off-grid spacing rounds
    down, so a 1.5-step spacing is no gap; off-grid bars are counted separately by :func:`check_series`).
    """
    ns = _ns(index)
    if len(ns) < 2:
        return []
    steps = np.diff(ns) // step.value
    where = np.flatnonzero(steps > 1)
    return [
        {"after": iso(index[i]), "before": iso(index[i + 1]), "missing": int(steps[i] - 1)} for i in where
    ]


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) positions (inclusive) of each run of True in ``flags``."""
    padded = np.concatenate([[False], flags, [False]]).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2], strict=True)]


def check_series(
    bars: pd.DataFrame,
    interval: str,
    *,
    sigma_k: float = 10.0,
    sigma_days: int = 30,
    stale_bars: int = 3,
    top: int = 10,
) -> dict:
    """Quality summary of one series (see the module docstring). ``top`` limits each example list.

    The rolling sigma uses the ``sigma_days`` worth of bars BEFORE each bar (at least half of them present),
    so a spike never hides in its own sigma. A stale run is ``stale_bars`` or more consecutive bars whose
    close equals the previous close.
    """
    step = step_of(interval)
    if bars.empty:
        raise ValueError("no bars to check")
    index = pd.DatetimeIndex(bars.index)
    ns = _ns(index)
    prices = bars.loc[:, list(PRICES)].to_numpy(dtype=float)
    o, h, lo, c = prices.T
    volume = bars["volume"].to_numpy(dtype=float)
    gaps = find_gaps(index, step)
    span = int((ns[-1] - ns[0]) // step.value) + 1
    out: dict = {
        "rows": len(bars),
        "start": iso(index[0]),
        "end": iso(index[-1]),
        "expected_bars": span,
        "off_grid": int((ns % step.value != 0).sum()),
        "duplicates": int(index.duplicated().sum()),
        "unsorted": bool(not index.is_monotonic_increasing),
        "gaps": len(gaps),
        "missing_bars": int(sum(g["missing"] for g in gaps)),
        "longest_gaps": sorted(gaps, key=lambda g: (-g["missing"], g["after"]))[:top],
        "non_positive": int((prices <= 0).any(axis=1).sum()),
        "ohlc_inconsistent": int(((h < np.maximum(o, c)) | (lo > np.minimum(o, c)) | (h < lo)).sum()),
        "zero_volume": int((volume == 0).sum()),
        "zero_volume_bars": [iso(t) for t in index[volume == 0][:top]],
    }
    with np.errstate(divide="ignore", invalid="ignore"):
        logr = np.diff(np.log(c), prepend=np.nan)
        upper = np.log(h / np.maximum(o, c))
        lower = np.log(np.minimum(o, c) / lo)
    window = max(2, int(pd.Timedelta(days=sigma_days) / step))
    sigma = pd.Series(logr).rolling(window, min_periods=window // 2).std().shift(1).to_numpy()
    valid = np.isfinite(sigma) & (sigma > 0)
    for name, values in (("extreme_moves", logr), ("extreme_wicks", np.maximum(upper, lower))):
        z = np.full(len(values), np.nan)
        z[valid] = np.abs(values[valid]) / sigma[valid]
        hits = np.flatnonzero(np.nan_to_num(z) > sigma_k)
        worst = hits[np.argsort(-z[hits], kind="stable")][:top]
        out[name] = len(hits)
        out[f"{name}_top"] = [
            {"ts": iso(index[i]), "log": round(float(values[i]), 6), "sigma": round(float(sigma[i]), 6),
             "k": round(float(z[i]), 1)}
            for i in worst
        ]
    same = np.concatenate([[False], c[1:] == c[:-1]])
    runs = [(a, b) for a, b in _runs(same) if b - a + 1 >= stale_bars]
    out["stale_runs"] = len(runs)
    longest = max(runs, key=lambda r: (r[1] - r[0], -r[0]), default=None)
    out["longest_stale"] = (
        None
        if longest is None
        else {"from": iso(index[longest[0] - 1]), "to": iso(index[longest[1]]), "unchanged_bars": longest[1] - longest[0] + 1}
    )
    return out


def compare_intervals(daily: pd.DataFrame, hourly: pd.DataFrame, top: int = 10) -> dict:
    """Daily bars against the hourly bars of the same source aggregated to days (``loaders.resample``).

    Compared on the days both have. OHLC should agree exactly; the volume up to float summation. Days whose
    hourly bars are incomplete still compare, so a mismatch can also mean hourly bars are missing or were
    dropped; the report lists the mismatched days.
    """
    agg = resample(hourly, "1D")
    common = daily.index.intersection(agg.index)
    d, a = daily.loc[common], agg.loc[common]
    diff = pd.DataFrame({col: d[col].to_numpy() != a[col].to_numpy() for col in PRICES}, index=common)
    bad = common[diff.any(axis=1).to_numpy()]
    dv, av = d["volume"].to_numpy(), a["volume"].to_numpy()
    vol = np.abs(av - dv) / np.where(dv > 0, dv, 1.0)  # relative; absolute where the daily volume is 0
    return {
        "days_compared": len(common),
        "daily_without_hourly": int(len(daily.index.difference(agg.index))),
        "mismatches": {col: int(diff[col].sum()) for col in PRICES},
        "mismatched_days": [
            {"ts": iso(t), "daily": [float(x) for x in d.loc[t, list(PRICES)]],
             "from_hourly": [float(x) for x in a.loc[t, list(PRICES)]]}
            for t in bad[:top]
        ],
        "volume_max_rel_diff": float(vol.max()) if len(vol) else 0.0,
    }


def cross_check(
    closes: Mapping[str, pd.Series],
    tolerance: float = 0.01,
    hourly: Mapping[str, pd.DatetimeIndex] | None = None,
) -> dict:
    """Same-day closes from several sources (``{name: close series indexed by close time}``).

    For every pair ``a/b`` on the days both have: the relative difference ``a / b - 1`` (median, 99th
    percentile and maximum of its absolute value, the median per calendar year of the trading day), and the
    days where ``|a / b - 1| > tolerance``. ``outliers`` lists every such day once, with every source's
    close that day and every pair's difference. Trading day = close time - 1 day. With ``hourly``
    (``{name: hourly close-time index}``) each outlier also gets ``hourly_bars``: how many of the day's 24
    hourly bars each source has, which shows when a daily close is stale because a venue stopped trading.
    """
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    names = sorted(closes)
    if len(names) < 2:
        raise ValueError("cross_check needs at least two sources")
    table = pd.concat({n: closes[n] for n in names}, axis=1, sort=True)
    pairs, flagged = [], {}
    for a, b in combinations(names, 2):
        both = table[[a, b]].dropna()
        rel = both[a] / both[b] - 1
        absrel = rel.abs()
        out_days = rel.index[(absrel > tolerance).to_numpy()]
        for t in out_days:
            flagged.setdefault(t, {})[f"{a}/{b}"] = round(float(rel.loc[t]), 6)
        years = (rel.index - pd.Timedelta(days=1)).year
        pairs.append(
            {
                "pair": f"{a}/{b}",
                "days": len(rel),
                "median": float(rel.median()) if len(rel) else None,
                "p99_abs": float(absrel.quantile(0.99)) if len(rel) else None,
                "max_abs": float(absrel.max()) if len(rel) else None,
                "max_day": _day(absrel.idxmax()) if len(rel) else None,
                "outliers": len(out_days),
                "median_by_year": {int(y): float(v) for y, v in rel.groupby(years).median().items()},
            }
        )
    outliers = []
    for t in sorted(flagged):
        row = table.loc[t]
        item = {
            "day": _day(t),
            "values": {n: float(row[n]) for n in names if pd.notna(row[n])},
            "pairs": flagged[t],
        }
        if hourly is not None:
            day = (t - pd.Timedelta(days=1), t)
            item["hourly_bars"] = {
                n: int(((idx > day[0]) & (idx <= day[1])).sum()) for n, idx in sorted(hourly.items())
            }
        outliers.append(item)
    return {"tolerance": tolerance, "sources": names, "pairs": pairs, "outliers": outliers}


def lag_alignment(a: pd.Series, b: pd.Series, step: pd.Timedelta, max_lag: int = 3) -> dict:
    """Are two sources' closes on the same clock? The median ``|log(a / b)|`` over common timestamps with
    ``a`` shifted by ``k`` steps, ``k = -max_lag .. max_lag``. Prices of one asset agree best when the
    timestamps mean the same instant, so ``best_lag`` must be 0; anything else is a time-zone or
    open/close-labelling error that the daily-vs-hourly check of one source can't see.
    """
    medians: dict[str, float | None] = {}
    for k in range(-max_lag, max_lag + 1):
        shifted = pd.Series(a.to_numpy(), index=a.index + k * step)
        common = shifted.index.intersection(b.index)
        ratio = np.log(shifted.loc[common].to_numpy() / b.loc[common].to_numpy())
        medians[str(k)] = float(np.median(np.abs(ratio))) if len(common) else None
    ranked = sorted((v, abs(int(k)), int(k)) for k, v in medians.items() if v is not None)
    best = ranked[0][2] if ranked else None
    return {"median_abs_log_diff": medians, "best_lag": best, "aligned": best == 0}


def _day(ts: pd.Timestamp) -> str:
    """The trading day of a daily bar closing at ``ts`` (its open date)."""
    return (pd.Timestamp(ts) - pd.Timedelta(days=1)).date().isoformat()


def window_coverage(
    index: pd.DatetimeIndex, interval: str, window: tuple[pd.Timestamp, pd.Timestamp | None]
) -> dict:
    """How a series covers a split ``window`` (a value of ``lab.config.splits()``; close-time rule).

    ``expected`` grid bars close in ``(start, end + 1 day]``; ``present`` of them exist; ``late_start_bars``
    are missing before the first bar in the window, ``early_end_bars`` after the last, and ``missing_inside``
    between them, listed in ``gaps`` (as :func:`find_gaps`). ``covered`` means the series spans the whole
    window (no late start or early end); ``complete`` means no bar is missing at all. An open-ended window
    ends at the series' last bar.
    """
    step = step_of(interval)
    start, end = window
    stop = end + pd.Timedelta(days=1) if end is not None else pd.Timestamp(index[-1])
    expected = max(0, int((stop - start) // step))
    inside = pd.DatetimeIndex(index[in_window(index, window)])
    out = {
        "window": [iso(start), iso(stop)],
        "expected": expected,
        "present": len(inside),
        "first": iso(inside[0]) if len(inside) else None,
        "last": iso(inside[-1]) if len(inside) else None,
    }
    if len(inside):
        late = int((inside[0] - start) // step) - 1
        early = int((stop - inside[-1]) // step)
    else:
        late, early = expected, 0
    out["late_start_bars"] = late
    out["early_end_bars"] = early
    out["missing_inside"] = expected - len(inside) - late - early
    out["gaps"] = find_gaps(inside, step)
    out["covered"] = late == 0 and early == 0
    out["complete"] = expected == len(inside)
    return out
