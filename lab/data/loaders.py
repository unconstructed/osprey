"""CSV loaders for the free bar sources, normalised to the lab's bar conventions.

Output of every loader: a DataFrame indexed by bar CLOSE time (tz-aware UTC ``DatetimeIndex`` named
``ts``, strictly increasing) with float64 ``open, high, low, close, volume`` plus ``trades`` (number
of trades in the bar, NaN where the file has none), ready for ``validate_bars``.

Cleaning, in this order:
1. A header row (first field not a number) is skipped; lines with more fields than the first line are
   skipped by the CSV reader.
2. Bad rows are dropped: a timestamp or price that is not a number, a price <= 0, negative volume,
   ``high < low``, or an open or close outside ``[low, high]``.
3. Rows are sorted by time (stable), then duplicate timestamps keep the LAST row in file order (a later
   row is taken to be a correction). Bad rows are dropped before de-duplication, so a bad correction
   never replaces a good row.

Epoch timestamps are detected per value by magnitude, so one file may mix units (Binance spot files
switched from milliseconds to microseconds on 2025-01-01): below 1e11 seconds, below 1e14
milliseconds, below 1e17 microseconds, else nanoseconds.

``attrs`` of a loaded frame records ``source``, ``rows_read`` (data rows parsed, header excluded),
``dropped_bad`` and ``dropped_duplicates`` for the data quality report.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset

from lab.runner.interface import validate_bars

PRICE_COLUMNS = ("open", "high", "low", "close")
BAR_COLUMNS = (*PRICE_COLUMNS, "volume")

# Kraken downloadable OHLCVT: no header; timestamp is the bar OPEN time in unix seconds.
KRAKEN_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "trades")
# data.binance.vision klines: optional header; open_time / close_time in ms (us from 2025 on).
BINANCE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)

_KRAKEN_INTERVAL_RE = re.compile(r"_(\d+)\.csv$", re.IGNORECASE)
# Non-negative integers below 9.2e18, so every accepted value fits in int64.
_EPOCH_RE = r"\d{1,18}|[0-8]\d{18}|9[01]\d{17}"
# Latest representable time in ns (just before pandas' Timestamp.max, 2262-04-11).
_MAX_NS = 9_200_000_000_000_000_000


def epoch_to_ns(values: pd.Series) -> pd.Series:
    """Epoch integers in s, ms, us or ns (unit detected per value) -> nullable Int64 nanoseconds.

    Anything that is not a non-negative integer, or lies beyond 2262 in its unit, becomes <NA>.
    Parsed from the text, never through float, so 16-digit microsecond stamps stay exact.
    """
    text = values.astype("str").str.strip()
    ok = text.str.fullmatch(_EPOCH_RE).fillna(False).to_numpy(dtype=bool)
    raw = text.where(ok, "0").astype("int64").to_numpy()
    factor = np.select([raw < 1e11, raw < 1e14, raw < 1e17], [1_000_000_000, 1_000_000, 1_000], 1)
    ok &= raw <= _MAX_NS // factor
    ns = np.where(ok, raw, 0) * factor
    return pd.Series(ns, index=values.index, dtype="Int64").where(ok)


def _read_fields(path: Path, min_fields: int) -> tuple[pd.DataFrame, str]:
    """Every CSV field as a string (header row removed) and the file name for messages."""
    try:
        raw = pd.read_csv(path, header=None, dtype=str, on_bad_lines="skip", skipinitialspace=True)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"{path.name}: file is empty") from exc
    if raw.shape[1] < min_fields:
        raise ValueError(f"{path.name}: expected at least {min_fields} columns, found {raw.shape[1]}")
    first = pd.to_numeric(raw.iloc[:1, 0], errors="coerce")
    if first.isna().all():  # header row
        raw = raw.iloc[1:]
    return raw.reset_index(drop=True), path.name


def _numbers(raw: pd.DataFrame, positions: dict[str, int]) -> pd.DataFrame:
    return pd.DataFrame(
        {name: pd.to_numeric(raw[pos], errors="coerce").astype(float) for name, pos in positions.items()}
    )


def _good_rows(bars: pd.DataFrame, ts_ok: np.ndarray) -> np.ndarray:
    """Row filter: valid timestamp and a valid OHLCV bar (NaN fails every comparison)."""
    o, h, lo, c, v = (bars[col].to_numpy() for col in BAR_COLUMNS)
    return (
        ts_ok
        & (o > 0)
        & (h > 0)
        & (lo > 0)
        & (c > 0)
        & (v >= 0)
        & (h >= lo)
        & (o >= lo)
        & (o <= h)
        & (c >= lo)
        & (c <= h)
    )


def _require_rows(good: np.ndarray, source: str) -> None:
    if not good.any():
        raise ValueError(f"{source}: no valid rows")


def _finish(bars: pd.DataFrame, close_ns: pd.Series, good: np.ndarray, source: str) -> pd.DataFrame:
    """Drop bad rows, sort (stable), de-duplicate keeping the last row, index by close time."""
    rows_read = len(bars)
    bars = bars.loc[good].copy()
    bars["ts"] = pd.to_datetime(close_ns.loc[bars.index].to_numpy(dtype="int64"), unit="ns", utc=True)
    bars = bars.sort_values("ts", kind="stable")
    duplicate = bars["ts"].duplicated(keep="last")
    bars = bars.loc[~duplicate].set_index("ts")
    bars = bars.loc[:, [*BAR_COLUMNS, "trades"]].astype(float)
    bars.attrs = {
        "source": source,
        "rows_read": rows_read,
        "dropped_bad": rows_read - int(good.sum()),
        "dropped_duplicates": int(duplicate.sum()),
    }
    return bars


def _kraken_interval(path: Path, open_ns: pd.Series, interval: pd.Timedelta | str | int | None) -> int:
    """Bar length in ns: ``interval`` (an int is minutes), else the file name, else the median spacing."""
    if interval is not None:
        step = pd.Timedelta(minutes=interval) if isinstance(interval, int) else pd.Timedelta(interval)
    elif match := _KRAKEN_INTERVAL_RE.search(path.name):
        step = pd.Timedelta(minutes=int(match.group(1)))
    else:
        spacing = np.diff(np.unique(open_ns.to_numpy(dtype="int64")))
        if len(spacing) == 0:
            raise ValueError(f"{path.name}: cannot infer the bar interval from one timestamp; pass interval=")
        step = pd.Timedelta(int(np.median(spacing)), unit="ns")
    if step <= pd.Timedelta(0):
        raise ValueError(f"{path.name}: bar interval must be positive, got {step}")
    return step.value


def load_kraken_ohlcvt(path: str | Path, interval: pd.Timedelta | str | int | None = None) -> pd.DataFrame:
    """Load a Kraken downloadable OHLCVT CSV (``timestamp,open,high,low,close,volume,trades``).

    The timestamp is the bar OPEN time; the index is open + interval (the bar close time). The interval
    comes from ``interval`` (a Timedelta or string such as ``"1h"``, or an int number of minutes), else
    the file name (``XBTUSD_1440.csv`` is daily, ``_60`` hourly), else the median spacing of the
    timestamps of the valid rows.
    """
    path = Path(path)
    raw, source = _read_fields(path, 6)
    open_ns = epoch_to_ns(raw[0])
    bars = _numbers(raw, {name: i for i, name in enumerate(BAR_COLUMNS, start=1)})
    bars["trades"] = pd.to_numeric(raw[6], errors="coerce").astype(float) if raw.shape[1] > 6 else np.nan
    good = _good_rows(bars, open_ns.notna().to_numpy(dtype=bool))
    _require_rows(good, source)
    step = _kraken_interval(path, open_ns.loc[good], interval)
    return _finish(bars, open_ns + step, good, source)


_SECOND_NS = 1_000_000_000


def load_binance_klines(path: str | Path) -> pd.DataFrame:
    """Load a data.binance.vision kline CSV (columns in ``BINANCE_COLUMNS`` order, header optional).

    ``close_time`` is the last moment of the bar (open + interval - 1 ms, or - 1 us), so the bar
    length is ``close_time - open_time`` rounded to the nearest second (which also accepts files whose
    ``close_time`` is the exact bar end) and the index is ``open_time + length``. A row whose length
    rounds to zero or less is bad. ``trades`` is Binance's ``count``.
    """
    path = Path(path)
    raw, source = _read_fields(path, 7)
    open_ns = epoch_to_ns(raw[0])
    close_ns = epoch_to_ns(raw[6])
    bars = _numbers(raw, {name: i for i, name in enumerate(BAR_COLUMNS, start=1)})
    bars["trades"] = pd.to_numeric(raw[8], errors="coerce").astype(float) if raw.shape[1] > 8 else np.nan
    # integer round-half-up to whole seconds (the 1 ms / 1 us end mark is far below half a second)
    length = (close_ns - open_ns + _SECOND_NS // 2) // _SECOND_NS * _SECOND_NS
    ts_ok = (length > 0).fillna(False).to_numpy(dtype=bool)
    good = _good_rows(bars, ts_ok)
    _require_rows(good, source)
    return _finish(bars, open_ns + length, good, source)


def resample(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate bars to a coarser ``rule`` (e.g. ``"1D"`` from hourly bars).

    open = first, high = max, low = min, close = last, volume = sum (and ``trades`` = sum if present;
    NaN when no input bar had a count). Buckets are right-closed and labelled by their close time,
    like the input bars: the daily bar labelled 2024-01-02 00:00 holds the hourly bars closing
    2024-01-01 01:00 .. 2024-01-02 00:00. Only complete buckets are kept: the trailing bucket the data
    does not reach the end of, a leading bucket that starts before the first input bar opened (input
    bar length = median spacing), and buckets with no input bars at all are dropped.
    """
    validate_bars(bars)
    offset = to_offset(rule)
    groups = bars.resample(offset, closed="right", label="right")
    out = pd.DataFrame(
        {
            "open": groups["open"].first(),
            "high": groups["high"].max(),
            "low": groups["low"].min(),
            "close": groups["close"].last(),
            "volume": groups["volume"].sum(),
        }
    )
    if "trades" in bars.columns:
        out["trades"] = groups["trades"].sum(min_count=1)
    out = out.dropna(subset=list(PRICE_COLUMNS))
    step = pd.Series(bars.index).diff().median()
    complete = (out.index - offset >= bars.index[0] - step) & (out.index <= bars.index[-1])
    out = out.loc[complete].astype(float)
    out.index = pd.DatetimeIndex(out.index, freq=None, name="ts")
    return out
