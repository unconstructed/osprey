"""External (non-bar) data in the catalog: Binance USD-M futures positioning, stored and read point in time.

Store (written by ``python -m lab.data.build --sources ...,binance_futures``): one Parquet file per symbol and
table, ``<catalog>/ext/binance_futures/<SYMBOL>/funding.parquet`` and ``metrics.parquet``, each recorded in
``SNAPSHOT.json`` under ``"external"`` with its SHA-256 (checked by :func:`read_table`). Columns: ``ts`` (the
source's timestamp, UTC), ``known_at`` (when the value was public, :mod:`lab.data.futures`), then the values.
Only values known strictly before the end of the validate window are stored: the build never downloads a file
of the test window, and :func:`read_table` refuses a store that holds anything later.

Point in time (:func:`positioning_at`, :func:`load_positioning`): the row of a bar closing at ``t`` uses only
values with ``known_at < t``, so a value published at or after a bar's close never appears in that bar's row.

- ``funding_last``: the newest funding rate (a fraction per funding interval, 8 hours for BTCUSDT and ETHUSDT);
  NaN when none is known or the newest is older than its interval plus :data:`FUNDING_SLACK` (an event missing).
- ``funding_mean_1d``, ``funding_count_1d`` (and ``_7d``): mean and number of the funding rates known in
  ``[t - k days, t)``; the mean is NaN unless their intervals cover the full ``k`` x 24 hours (a missing event
  makes the window incomplete). With 8-hour funding the 7-day mean is the mean of the last 21 rates.
- ``oi_last`` (contracts = base units), ``oi_value_last`` (USDT), ``ls_account_last`` (long/short ratio of all
  accounts), ``ls_top_account_last`` and ``ls_top_position_last`` (top traders, by accounts and by positions):
  the newest valid value; NaN when none is known within :data:`METRICS_MAX_AGE`.
- ``oi_change_1d``, ``oi_change_7d``: ``oi_last(t) / oi_last(t - k days) - 1``, each side by the same rule.

Nothing is forward-filled beyond those ages, and the request can't reach into the test window:
:func:`load_positioning` raises :class:`HoldoutWindowError` for an ``end`` after the last validate bar's close.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import splits
from lab.data import futures as fu
from lab.data.sources import sha256_file

EXT_DIR = "ext/binance_futures"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TABLES = ("funding", "metrics")
COLUMNS = {
    "funding": ("ts", "known_at", "rate", "interval_hours"),
    "metrics": ("ts", "known_at", *fu.METRIC_FIELDS.values()),
}
FREQS = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1)}
FUNDING_SLACK = pd.Timedelta(minutes=5)
METRICS_MAX_AGE = pd.Timedelta(hours=1)
LAST_COLUMNS = {  # output column -> metrics column
    "oi_last": "open_interest",
    "oi_value_last": "open_interest_value",
    "ls_account_last": "account_ls_ratio",
    "ls_top_account_last": "top_account_ls_ratio",
    "ls_top_position_last": "top_position_ls_ratio",
}
FUNDING_WINDOWS = (1, 7)  # days
OUTPUT_COLUMNS = (
    "funding_last", "funding_mean_1d", "funding_count_1d", "funding_mean_7d", "funding_count_7d", *LAST_COLUMNS,
    "oi_change_1d", "oi_change_7d",
)
RULES = {
    "known_at": "funding: calc_time; metrics: create_time + 5 min (create_time is the start of the 5-minute "
    "period in the newer files, its end in the older ones; checked per day, SNAPSHOT.json checks.metrics_timing)",
    "row_at_close_t": "only values with known_at < t",
    "funding_last": f"newest rate, NaN if older than its interval + {fu.describe(FUNDING_SLACK)}",
    "funding_mean_kd": "mean of the rates known in [t - k days, t), NaN unless their intervals cover k x 24 hours",
    "metrics_last": f"newest valid value, NaN if older than {fu.describe(METRICS_MAX_AGE)}",
    "oi_change_kd": "oi_last(t) / oi_last(t - k days) - 1",
}


class HoldoutWindowError(ValueError):
    """A request, or a stored value, reaches into the test window (config/splits.yaml)."""


def holdout_cut(config_dir: Path | None = None) -> pd.Timestamp:
    """Close time of the last bar of the validate window (its last day + 1 day, UTC). Bars of the test window
    close after it; every positioning value stored or used is known strictly before it."""
    return splits(config_dir)["validate"][1] + pd.Timedelta(days=1)


def table_path(catalog_dir: str | Path, symbol: str, table: str) -> Path:
    if symbol not in SYMBOLS or table not in TABLES:
        raise ValueError(f"symbol must be one of {SYMBOLS} and table one of {TABLES}; got {symbol!r}, {table!r}")
    return Path(catalog_dir) / EXT_DIR / symbol / f"{table}.parquet"


def write_table(catalog_dir: str | Path, symbol: str, table: str, frame: pd.DataFrame) -> dict:
    """Write one stored table and return its SNAPSHOT.json entry (path relative to the catalog, SHA-256, rows,
    first and last ``ts`` and ``known_at``)."""
    if tuple(frame.columns) != COLUMNS[table]:
        raise ValueError(f"{table} columns must be {COLUMNS[table]}, got {tuple(frame.columns)}")
    path = table_path(catalog_dir, symbol, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return {
        "symbol": symbol,
        "table": table,
        "path": path.relative_to(catalog_dir).as_posix(),
        "sha256": sha256_file(path),
        "rows": len(frame),
        "first_ts": frame["ts"].iloc[0].isoformat(),
        "last_ts": frame["ts"].iloc[-1].isoformat(),
        "first_known_at": frame["known_at"].iloc[0].isoformat(),
        "last_known_at": frame["known_at"].iloc[-1].isoformat(),
    }


def read_table(
    catalog_dir: str | Path, symbol: str, table: str, sha256: str | None = None, config_dir: Path | None = None
) -> pd.DataFrame:
    """One stored table, checked: its SHA-256 must equal ``sha256`` (default: the one in SNAPSHOT.json), times
    must be strictly increasing, and no value may be known at or after :func:`holdout_cut`."""
    catalog_dir = Path(catalog_dir)
    path = table_path(catalog_dir, symbol, table)
    if sha256 is None:
        entries = json.loads((catalog_dir / "SNAPSHOT.json").read_text()).get("external", [])
        found = [e["sha256"] for e in entries if e["symbol"] == symbol and e["table"] == table]
        if len(found) != 1:
            raise FileNotFoundError(f"SNAPSHOT.json in {catalog_dir} lists no {symbol} {table} table; build with "
                                    "--sources ...,binance_futures")
        sha256 = found[0]
    if sha256_file(path) != sha256:
        raise ValueError(f"{path}: SHA-256 does not match the snapshot; the file was changed after the build")
    frame = pd.read_parquet(path)
    if tuple(frame.columns) != COLUMNS[table]:
        raise ValueError(f"{path}: columns {tuple(frame.columns)}, expected {COLUMNS[table]}")
    ts, known = pd.DatetimeIndex(frame["ts"]), pd.DatetimeIndex(frame["known_at"])
    if not (ts.is_monotonic_increasing and ts.is_unique and known.is_monotonic_increasing):
        raise ValueError(f"{path}: times are not strictly increasing")
    cut = holdout_cut(config_dir)
    if len(frame) and known[-1] >= cut:
        raise HoldoutWindowError(f"{path}: holds values known at or after {cut.isoformat()} (the test window)")
    return frame


def _ns(values) -> np.ndarray:
    return np.asarray(pd.DatetimeIndex(values).as_unit("ns").asi8, dtype=np.int64)


def _asof(known: np.ndarray, values: np.ndarray, closes: np.ndarray, max_age: np.ndarray) -> np.ndarray:
    """Newest of ``values`` with ``known < close`` per close, NaN if none or older than its ``max_age`` (ns)."""
    pos = np.searchsorted(known, closes, side="left") - 1
    out = np.full(len(closes), np.nan)
    ok = pos >= 0
    p = pos[ok]
    fresh = closes[ok] - known[p] <= max_age[p]
    out[np.flatnonzero(ok)[fresh]] = values[p][fresh]
    assert np.all(known[p] < closes[ok]), "a value known at or after the close was selected"
    return out


def _metric_asof(metrics: pd.DataFrame, column: str, closes: np.ndarray) -> np.ndarray:
    have = metrics[column].notna().to_numpy()
    known = _ns(metrics["known_at"])[have]
    max_age = np.full(len(known), METRICS_MAX_AGE.value, dtype=np.int64)
    return _asof(known, metrics[column].to_numpy(dtype=float)[have], closes, max_age)


def positioning_at(funding: pd.DataFrame, metrics: pd.DataFrame, closes) -> pd.DataFrame:
    """The positioning row of every bar close in ``closes`` (module docstring), from stored tables.

    ``closes``: UTC close times (any order is kept). Uses only ``known_at``, never ``ts``.
    """
    index = pd.DatetimeIndex(closes).as_unit("us").rename("ts")
    t = _ns(index)
    out = pd.DataFrame(index=index)
    f_known = _ns(funding["known_at"])
    rate = funding["rate"].to_numpy(dtype=float)
    hours = funding["interval_hours"].to_numpy(dtype=float)
    max_age = (hours * 3600e9).astype(np.int64) + FUNDING_SLACK.value
    out["funding_last"] = _asof(f_known, rate, t, max_age)
    hi = np.searchsorted(f_known, t, side="left")
    for days in FUNDING_WINDOWS:
        lo = np.searchsorted(f_known, t - days * FREQS["1d"].value, side="left")
        count = hi - lo
        mean = np.full(len(t), np.nan)
        for i in np.flatnonzero(count):
            if hours[lo[i] : hi[i]].sum() >= 24 * days:
                mean[i] = rate[lo[i] : hi[i]].mean()
        out[f"funding_mean_{days}d"] = mean
        out[f"funding_count_{days}d"] = count.astype(np.int64)
    for name, column in LAST_COLUMNS.items():
        out[name] = _metric_asof(metrics, column, t)
    for k in (1, 7):
        before = _metric_asof(metrics, "open_interest", t - pd.Timedelta(days=k).value)
        out[f"oi_change_{k}d"] = out["oi_last"].to_numpy() / before - 1
    return out


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def load_positioning(
    symbol: str,
    freq: str = "1d",
    start=None,
    end=None,
    catalog_dir: str | Path = "data/catalog",
    config_dir: Path | None = None,
) -> pd.DataFrame:
    """Positioning per bar close of ``symbol`` (``"BTCUSDT"`` or ``"ETHUSDT"``) on the ``freq`` grid
    (``"1d"`` or ``"1h"``), for closes in ``[start, end]`` (naive means UTC; rounded inward to the grid).

    ``end`` defaults to, and may not exceed, :func:`holdout_cut` (the last validate bar's close):
    :class:`HoldoutWindowError` otherwise. ``start`` defaults to the first close after the first stored value.
    Every close of the grid is a row (NaN where nothing is known; join to bars with ``reindex(bars.index)``).
    ``attrs``: ``snapshot_id``, ``symbol``, ``freq``, ``cut`` and the ``rules``.
    """
    if symbol not in SYMBOLS or freq not in FREQS:
        raise ValueError(f"symbol must be one of {SYMBOLS} and freq one of {sorted(FREQS)}; got {symbol!r}, {freq!r}")
    cut = holdout_cut(config_dir)
    end = cut if end is None else _utc(end)
    if end > cut:
        raise HoldoutWindowError(
            f"end {end.isoformat()} is after {cut.isoformat()}, the close of the last validate bar: the test "
            "window is opened once per strategy by the backtest-auditor, never through this loader"
        )
    catalog_dir = Path(catalog_dir)
    funding = read_table(catalog_dir, symbol, "funding", config_dir=config_dir)
    metrics = read_table(catalog_dir, symbol, "metrics", config_dir=config_dir)
    step = FREQS[freq]
    if start is None:
        start = min(funding["known_at"].iloc[0], metrics["known_at"].iloc[0]).floor(step) + step
    start = _utc(start).ceil(step)
    closes = pd.date_range(start, end.floor(step), freq=step)
    if closes.empty:
        raise ValueError(f"no {freq} close between start {start.isoformat()} and end {end.isoformat()}")
    out = positioning_at(funding, metrics, closes)
    assert out.index[-1] <= cut, "a row closes in the test window"
    sid = json.loads((catalog_dir / "SNAPSHOT.json").read_text())["snapshot_id"]
    out.attrs = {"snapshot_id": sid, "symbol": symbol, "freq": freq, "cut": cut.isoformat(), "rules": dict(RULES)}
    return out
