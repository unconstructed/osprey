"""The Nautilus data catalog: write instruments and bars (v2 ``ParquetDataCatalog``) and read them back.

Instruments are spot ``CurrencyPair`` s: ``BTC/USD.KRAKEN``, ``ETH/USD.KRAKEN``, ``BTCUSDT.BINANCE``,
``ETHUSDT.BINANCE``, ``BTC-USD.COINBASE``, ``ETH-USD.COINBASE``. The price precision comes from the data
(the most decimals any price of the instrument has, in its shortest exact decimal form, so no price is
rounded); the size precision is 8. Bar types are ``<instrument>-1-DAY-LAST-EXTERNAL`` and
``<instrument>-1-HOUR-LAST-EXTERNAL``.

Timestamps: ``ts_event = ts_init = bar CLOSE time`` in ns. NautilusTrader v2 requires ``ts_init`` to be the
close of the interval for bar execution ("This prevents the complete bar from becoming visible before it
formed", docs/concepts/backtesting/bar-execution.md of the v2.0.0rc9 reference clone), and it is the lab's
bar index convention.

:func:`load_bars` returns the lab's standard bars. Prices and volumes are converted with ``float(Price)``
and ``float(Quantity)``, exactly as a live Nautilus strategy converts them (the ``FeatureBuffer`` path), so
batch and live features agree bit for bit. That conversion can differ from the source CSV's float by one
unit in the last place (TESTING.md 4a.8); the ``Price`` itself is exact. Volumes are stored at 8 decimals:
Kraken volumes carry float-summation digits beyond that, so they are rounded to 1e-8 (recorded by the
build). :func:`stored_values` gives the floats the catalog will return for given bars.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from nautilus_trader.model import (
    Bar,
    BarType,
    Currency,
    CurrencyPair,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog

from lab.data.loaders import BAR_COLUMNS, PRICE_COLUMNS

SNAPSHOT_FILE = "SNAPSHOT.json"
SIZE_PRECISION = 8
MAX_PRICE_PRECISION = 12
BAR_SPECS = {"1d": "1-DAY", "1h": "1-HOUR"}
SNAPSHOT_ID_RE = re.compile(r"[0-9a-f]{16}")

# (source, coin) -> (instrument id, raw symbol at the venue, base, quote)
INSTRUMENTS = {
    ("kraken", "BTC"): ("BTC/USD.KRAKEN", "XBTUSD", "BTC", "USD"),
    ("kraken", "ETH"): ("ETH/USD.KRAKEN", "ETHUSD", "ETH", "USD"),
    ("binance", "BTC"): ("BTCUSDT.BINANCE", "BTCUSDT", "BTC", "USDT"),
    ("binance", "ETH"): ("ETHUSDT.BINANCE", "ETHUSDT", "ETH", "USDT"),
    ("coinbase", "BTC"): ("BTC-USD.COINBASE", "BTC-USD", "BTC", "USD"),
    ("coinbase", "ETH"): ("ETH-USD.COINBASE", "ETH-USD", "ETH", "USD"),
}


def bar_type(instrument: str, interval: str) -> str:
    """``"BTC/USD.KRAKEN", "1d"`` -> ``"BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL"``."""
    if interval not in BAR_SPECS:
        raise ValueError(f"interval must be one of {sorted(BAR_SPECS)}, got {interval!r}")
    return f"{instrument}-{BAR_SPECS[interval]}-LAST-EXTERNAL"


def decimals(values: np.ndarray) -> int:
    """Most decimal places among ``values`` written in their shortest exact (round-trip) decimal form."""
    most = 0
    for x in np.unique(np.asarray(values, dtype=float)):
        if not np.isfinite(x):
            raise ValueError(f"cannot take the precision of {x}")
        text = np.format_float_positional(x, unique=True, trim="-")
        most = max(most, len(text.partition(".")[2]))
    return most


def price_precision(*frames: pd.DataFrame) -> int:
    """Price precision for an instrument from all its bars (every interval): the most decimals of any price."""
    p = max(decimals(f.loc[:, list(PRICE_COLUMNS)].to_numpy().ravel()) for f in frames)
    if p > MAX_PRICE_PRECISION:
        raise ValueError(f"prices with {p} decimals look like float noise, not exchange prices")
    return p


def make_instrument(instrument_id: str, raw_symbol: str, base: str, quote: str, precision: int) -> CurrencyPair:
    """A spot ``CurrencyPair`` with the given price precision and size precision 8."""
    return CurrencyPair(
        InstrumentId.from_str(instrument_id),
        Symbol(raw_symbol),
        Currency.from_str(base),
        Currency.from_str(quote),
        precision,
        SIZE_PRECISION,
        Price(10.0**-precision, precision),
        Quantity(10.0**-SIZE_PRECISION, SIZE_PRECISION),
        0,
        0,
    )


def to_nautilus(bars: pd.DataFrame, bar_type_str: str, precision: int) -> list[Bar]:
    """Standard bars -> Nautilus ``Bar`` objects with ``ts_event = ts_init = close time`` (ns)."""
    bt = BarType.from_str(bar_type_str)
    ts = np.asarray(pd.DatetimeIndex(bars.index).as_unit("ns").asi8, dtype=np.int64)
    cols = [bars[c].to_numpy(dtype=float).tolist() for c in BAR_COLUMNS]
    return [
        Bar(bt, Price(o, precision), Price(h, precision), Price(lo, precision), Price(c, precision),
            Quantity(v, SIZE_PRECISION), int(t), int(t))
        for o, h, lo, c, v, t in zip(*cols, ts.tolist(), strict=True)
    ]


def stored_values(bars: pd.DataFrame, precision: int) -> pd.DataFrame:
    """The OHLCV floats :func:`load_bars` returns for ``bars`` written at ``precision``."""
    out = pd.DataFrame(index=bars.index)
    for col in PRICE_COLUMNS:
        out[col] = [float(Price(x, precision)) for x in bars[col].to_numpy(dtype=float).tolist()]
    out["volume"] = [float(Quantity(x, SIZE_PRECISION)) for x in bars["volume"].to_numpy(dtype=float).tolist()]
    return out


def write_catalog(catalog_dir: str | Path, instruments: list[CurrencyPair], series: dict[str, list[Bar]]) -> None:
    """Write ``instruments`` and each bar type's bars (sorted by close time) into a new or empty catalog."""
    catalog_dir = Path(catalog_dir)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_dir))
    catalog.write_instruments(instruments)
    for bars in series.values():
        catalog.write_bars(bars)


def snapshot_id(catalog_dir: str | Path = "data/catalog") -> str:
    """The snapshot ID recorded in ``<catalog_dir>/SNAPSHOT.json`` (16 lowercase hex characters)."""
    path = Path(catalog_dir) / SNAPSHOT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found: build the catalog with `uv run python -m lab.data.build`")
    sid = json.loads(path.read_text()).get("snapshot_id")
    if not isinstance(sid, str) or not SNAPSHOT_ID_RE.fullmatch(sid):
        raise ValueError(f"{path}: snapshot_id must be 16 lowercase hex characters, got {sid!r}")
    return sid


def _ns(value) -> int | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.as_unit("ns").value)


def load_bars(
    instrument: str,
    interval: str = "1d",
    start=None,
    end=None,
    catalog_dir: str | Path = "data/catalog",
) -> pd.DataFrame:
    """Bars of ``instrument`` (e.g. ``"BTC/USD.KRAKEN"``) and ``interval`` (``"1d"`` or ``"1h"``) from the catalog.

    ``start`` / ``end`` (anything ``pd.Timestamp`` takes; naive means UTC) bound the bar CLOSE times, both
    inclusive. Returns the standard bars: index ``ts`` (UTC close time, microsecond resolution), float64
    ``open, high, low, close, volume`` converted like the live path (module docstring), and
    ``attrs = {"snapshot_id", "bar_type", "instrument"}``. Raises ``FileNotFoundError`` without a
    ``SNAPSHOT.json`` (an unsnapshotted catalog can't be traced) and ``ValueError`` when no bar matches.
    """
    catalog_dir = Path(catalog_dir)
    sid = snapshot_id(catalog_dir)
    bt = bar_type(instrument, interval)
    lo, hi = _ns(start), _ns(end)
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"start {start} is after end {end}")
    bars = ParquetDataCatalog(str(catalog_dir)).query_bars([bt], start=lo, end=hi)
    if not bars:
        raise ValueError(f"no {bt} bars in {catalog_dir} for start={start}, end={end}")
    ts = np.array([b.ts_init for b in bars], dtype=np.int64)
    if any(b.ts_event != b.ts_init for b in bars):
        raise ValueError(f"{bt}: ts_event differs from ts_init; the catalog does not follow the close-time rule")
    index = pd.DatetimeIndex(pd.to_datetime(ts, unit="ns", utc=True)).as_unit("us").rename("ts")
    frame = pd.DataFrame(
        {col: np.array([float(getattr(b, col)) for b in bars], dtype=float) for col in BAR_COLUMNS},
        index=index,
    )
    keep = np.ones(len(frame), dtype=bool)
    if lo is not None:
        keep &= ts >= lo
    if hi is not None:
        keep &= ts <= hi
    frame = frame.loc[keep]
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError(f"{bt}: bars in the catalog are not strictly increasing in time")
    frame.attrs = {"snapshot_id": sid, "bar_type": bt, "instrument": instrument}
    return frame
