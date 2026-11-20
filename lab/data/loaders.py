"""Loaders for the free bar sources (Kraken and Binance CSV, Coinbase JSON candle pages), normalised to the
lab's bar conventions.

Output of every loader: a DataFrame indexed by bar CLOSE time (tz-aware UTC ``DatetimeIndex`` named
``ts``, microsecond resolution like every bar index in the lab, strictly increasing) with float64
``open, high, low, close, volume`` plus ``trades`` (number of trades in the bar, NaN where the file
has none), ready for ``validate_bars``.

Cleaning, in this order:
1. A header row (first field not a number) is skipped. Lines are read against the format's full width
   (7 fields for Kraken, 12 for Binance): a shorter line gets NaN for its missing fields (e.g. no trades
   count), a line with MORE fields than that is skipped and counted in ``dropped_bad``.
2. Bad rows are dropped: a timestamp or price that is not a number, a price <= 0, negative volume,
   ``high < low``, or an open or close outside ``[low, high]``.
3. Rows are sorted by time (stable), then duplicate timestamps keep the LAST row in file order (a later
   row is taken to be a correction). Bad rows are dropped before de-duplication, so a bad correction
   never replaces a good row.

Epoch timestamps are detected per value by magnitude, so one file may mix units (Binance spot files
switched from milliseconds to microseconds on 2025-01-01): below 1e11 seconds, below 1e14
milliseconds, below 1e17 microseconds, else nanoseconds.

``attrs`` of a loaded frame records ``source``, ``rows_read`` (data lines read, header excluded, over-wide
lines included), ``dropped_bad`` and ``dropped_duplicates`` for the data quality report.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Sequence
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


def _epoch(values: pd.Series) -> tuple[pd.Series, np.ndarray]:
    """Epoch integers (unit detected per value) -> (nullable Int64 nanoseconds, ns per unit of each value).

    Anything that is not a non-negative integer, or lies beyond 2262 in its unit, becomes <NA>.
    Parsed from the text, never through float, so 16-digit microsecond stamps stay exact.
    """
    text = values.astype("str").str.strip()
    ok = text.str.fullmatch(_EPOCH_RE).fillna(False).to_numpy(dtype=bool)
    raw = text.where(ok, "0").astype("int64").to_numpy()
    unit = np.select([raw < 1e11, raw < 1e14, raw < 1e17], [1_000_000_000, 1_000_000, 1_000], 1)
    ok = ok & (raw <= _MAX_NS // unit)  # not in place: pandas 3 hands out read-only arrays
    ns = pd.Series(np.where(ok, raw, 0) * unit, index=values.index, dtype="Int64").where(ok)
    return ns, unit


def epoch_to_ns(values: pd.Series) -> pd.Series:
    """Epoch integers in s, ms, us or ns (unit detected per value) -> nullable Int64 nanoseconds.

    Anything that is not a non-negative integer, or lies beyond 2262 in its unit, becomes <NA>.
    """
    return _epoch(values)[0]


def _read_fields(path: Path, min_fields: int, width: int) -> tuple[pd.DataFrame, str, int]:
    """Every CSV field as a string in ``width`` columns (header row removed), the file name for messages, and
    the number of lines skipped for having more than ``width`` fields.

    Each line is read whole and split here, so the field count is per line: a shorter line is padded with NaN
    (a first line without the optional trades field can't make the reader drop every later full line, as
    pandas' ``on_bad_lines="skip"`` did), and an over-wide line is counted, never silently lost or shifted.
    Whitespace inside a line is removed (the sources are plain numbers; this replaces ``skipinitialspace``).
    """
    lines = pd.read_csv(
        path, header=None, names=["line"], sep="\x1e", dtype=str, quoting=csv.QUOTE_NONE
    )["line"]
    if lines.empty:
        raise ValueError(f"{path.name}: file is empty")
    lines = lines.str.replace(r"\s+", "", regex=True)
    n_fields = lines.str.count(",").to_numpy(dtype=int) + 1
    over_wide = n_fields > width
    if over_wide.all():
        raise ValueError(f"{path.name}: all {len(lines)} lines have more than {width} fields")
    found = int(n_fields[~over_wide].max())
    if found < min_fields:
        raise ValueError(f"{path.name}: expected at least {min_fields} columns, found {found}")
    raw = lines[~over_wide].str.split(",", expand=True).reindex(columns=range(width))
    raw = raw.replace("", None)  # an empty field is a missing value, as in read_csv
    first = pd.to_numeric(raw.iloc[:1, 0], errors="coerce")
    if first.isna().all():  # header row
        raw = raw.iloc[1:]
    return raw.reset_index(drop=True), path.name, int(over_wide.sum())


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


def _finish(
    bars: pd.DataFrame, close_ns: pd.Series, good: np.ndarray, source: str, over_wide: int
) -> pd.DataFrame:
    """Drop bad rows, sort (stable), de-duplicate keeping the last row, index by close time."""
    rows_read = len(bars) + over_wide
    bars = bars.loc[good].copy()
    # microsecond resolution, like every other bar index in the lab (pandas 3 default); no source has finer
    stamps = pd.to_datetime(close_ns.loc[bars.index].to_numpy(dtype="int64"), unit="ns", utc=True)
    bars["ts"] = stamps.as_unit("us")
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
    raw, source, over_wide = _read_fields(path, 6, len(KRAKEN_COLUMNS))
    open_ns = epoch_to_ns(raw[0])
    bars = _numbers(raw, {name: i for i, name in enumerate(BAR_COLUMNS, start=1)})
    bars["trades"] = pd.to_numeric(raw[6], errors="coerce").astype(float)
    good = _good_rows(bars, open_ns.notna().to_numpy(dtype=bool))
    _require_rows(good, source)
    step = _kraken_interval(path, open_ns.loc[good], interval)
    return _finish(bars, open_ns + step, good, source, over_wide)


_SECOND_NS = 1_000_000_000


def load_binance_klines(path: str | Path, interval: pd.Timedelta | str | None = None) -> pd.DataFrame:
    """Load a data.binance.vision kline CSV (columns in ``BINANCE_COLUMNS`` order, header optional).

    ``close_time`` is the last moment of the bar, ``open_time + interval - 1 unit`` (1 ms, or 1 us in
    the newer files; the unit is detected per value). The bar length is therefore
    ``close_time + 1 unit - open_time``, rounded to the nearest second (so a file whose ``close_time``
    is the exact bar end in ms or us also loads correctly), and the index is ``open_time + length``.
    A row whose length rounds to zero or less is bad. ``trades`` is Binance's ``count``.

    With ``interval`` (e.g. ``"1h"``) the bars are put on that grid instead, for the catalog. Real files
    have rows that are not whole grid bars: bars cut short by exchange maintenance (open on the grid,
    early ``close_time``) and, in February 2018, a run of hourly bars shifted off the grid by 28m14.789s.
    Grid mode labels a bar ``open_time + interval`` when its open lies on the grid and its length is in
    ``(0, interval + 1 s]`` (a short bar holds every trade of its interval: the exchange was halted for the
    rest); a bar longer than that is bad; a bar whose open is off the grid is dropped and counted. ``attrs``
    then also has ``dropped_off_grid`` (count), ``off_grid_opens`` and ``short_bars`` (``[open ISO, seconds]``
    of the bars kept although shorter than ``interval - 1 s``).
    """
    path = Path(path)
    raw, source, over_wide = _read_fields(path, 7, len(BINANCE_COLUMNS))
    open_ns = epoch_to_ns(raw[0])
    close_ns, close_unit = _epoch(raw[6])
    bars = _numbers(raw, {name: i for i, name in enumerate(BAR_COLUMNS, start=1)})
    bars["trades"] = pd.to_numeric(raw[8], errors="coerce").astype(float)
    # integer round-half-up to whole seconds
    length = (close_ns + close_unit - open_ns + _SECOND_NS // 2) // _SECOND_NS * _SECOND_NS
    ts_ok = (length > 0).fillna(False).to_numpy(dtype=bool)
    if interval is None:
        good = _good_rows(bars, ts_ok)
        _require_rows(good, source)
        return _finish(bars, open_ns + length, good, source, over_wide)
    step = pd.Timedelta(interval).value
    if step <= 0:
        raise ValueError(f"{source}: bar interval must be positive, got {interval}")
    ts_ok &= (length <= step + _SECOND_NS).fillna(False).to_numpy(dtype=bool)
    good = _good_rows(bars, ts_ok)
    on_grid = (open_ns % step == 0).fillna(False).to_numpy(dtype=bool)
    keep = good & on_grid
    _require_rows(keep, source)
    out = _finish(bars, open_ns + step, keep, source, over_wide)
    off = good & ~on_grid
    short = keep & (length < step - _SECOND_NS).fillna(False).to_numpy(dtype=bool)

    def iso(ns: pd.Series) -> list[str]:
        return [t.isoformat() for t in pd.to_datetime(ns.to_numpy(dtype="int64"), unit="ns", utc=True)]

    out.attrs["dropped_bad"] -= int(off.sum())
    out.attrs["dropped_off_grid"] = int(off.sum())
    out.attrs["off_grid_opens"] = iso(open_ns[off])
    out.attrs["short_bars"] = [
        [t, int(n) // _SECOND_NS] for t, n in zip(iso(open_ns[short]), length[short], strict=True)
    ]
    return out


COINBASE_FIELDS = ("time", "low", "high", "open", "close", "volume")


def _coinbase_row(row) -> list:
    """One candle as [time, low, high, open, close, volume]; a malformed row becomes all None (bad)."""
    numeric = isinstance(row, list) and len(row) == len(COINBASE_FIELDS)
    numeric = numeric and all(isinstance(x, int | float) and not isinstance(x, bool) for x in row)
    if not numeric or not isinstance(row[0], int):
        return [None] * len(COINBASE_FIELDS)
    return row


def load_coinbase_candles(paths: Sequence[str | Path], granularity: int = 86_400) -> pd.DataFrame:
    """Load Coinbase Exchange REST candle pages (``GET /products/{id}/candles`` answers saved as JSON).

    Each page is a JSON list of ``[time, low, high, open, close, volume]`` rows (NOTE the order), newest
    first, with ``time`` the bar OPEN in unix seconds; the index is ``time + granularity``. Pages are read
    in the order given; rows go through the same cleaning as the CSV loaders (a row that is not six numbers
    with an integer time is bad; duplicates keep the last row in page order). ``trades`` is NaN (the API
    has no trade count). A page that is not a JSON list raises ``ValueError``.
    """
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("no Coinbase pages given")
    rows = []
    for path in paths:
        page = json.loads(path.read_text())
        if not isinstance(page, list):
            raise ValueError(f"{path.name}: a candles page must be a JSON list")
        rows += [_coinbase_row(row) for row in page]
    source = f"{paths[0].parent.name} ({len(paths)} pages)"
    if not rows:
        raise ValueError(f"{source}: no valid rows")
    table = pd.DataFrame(rows, columns=list(COINBASE_FIELDS))
    bars = table.loc[:, list(BAR_COLUMNS)].astype(float)
    bars["trades"] = np.nan
    open_ns = epoch_to_ns(table["time"].astype("Int64").astype(str))
    good = _good_rows(bars, open_ns.notna().to_numpy(dtype=bool))
    _require_rows(good, source)
    return _finish(bars, open_ns + granularity * _SECOND_NS, good, source, 0)


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
