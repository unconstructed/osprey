"""Two-asset bar panel (BTC and ETH) from the catalog, for the multi-asset reference runner.

:func:`load_panel` returns the panel in the pinned format the runner reads:

- index ``ts``: UTC bar CLOSE time, microsecond unit, strictly increasing, no duplicates;
- columns: a 2-level MultiIndex named ``("asset", "field")``, assets :data:`ASSETS` = ``("BTC", "ETH")`` in that
  order, and per asset exactly :data:`FIELDS` = ``open, high, low, close, volume`` (float64). ``panel[asset]``
  passes ``lab.runner.interface.validate_bars``;
- ``attrs``: exactly ``snapshot_id`` (str), ``instruments`` (``{asset: instrument id}``), ``bar_type``
  (``{asset: Nautilus bar type}``) and ``alignment`` (below).

USDC is cash (price 1) and has no bars.

Rules:

- **Sources.** ``"KRAKEN"``: ``BTC/USD.KRAKEN`` and ``ETH/USD.KRAKEN``; ``"BINANCE"``: ``BTCUSDT.BINANCE`` and
  ``ETHUSDT.BINANCE`` (:data:`lab.data.catalog.INSTRUMENTS`). Intervals ``"1d"`` and ``"1h"``.
- **Train and validate only.** Bars are kept when they close in the train or the validate window
  (``lab.config.in_window``, the close-time rule): with the fixed splits, closes in
  ``(2017-01-01 00:00, 2024-07-01 00:00]``. No bar closing at or before the first train midnight is returned.
- **Test window.** ``last_close`` is required. A ``last_close`` after :func:`lab.data.external.holdout_cut` (the
  close of the last validate bar, 2024-07-01 00:00 UTC) raises :class:`HoldoutWindowError` before anything is
  read, and so does any bar a loader returns that closes after it (the guard of
  ``lab.models.dips.load_study_bars``). Exactly the last validate close is allowed.
- **Alignment.** A close is kept only where BOTH assets have a bar; nothing is invented, interpolated or
  forward-filled. ``attrs["alignment"]`` records it:

  - ``rule``: the rule in words;
  - ``request``: ``{"start", "last_close"}`` as ISO strings (``start`` is ``None`` when not given);
  - ``rows``: ``{asset: bars in the requested range and windows, before the join}``;
  - ``common``: rows of the panel; ``first``, ``last``: its first and last close (ISO);
  - ``dropped``: ``{asset: {"count", "closes"}}``, the closes where that asset has a bar and the other has none
    (the asset's bar is dropped), ISO strings in time order;
  - ``missing``: ``{"count", "closes"}``, the grid closes strictly between ``first`` and ``last`` with no panel
    row (a close dropped for either asset, or one neither asset has). A panel return over such a gap spans
    more than one bar.

A loader that returns bars outside the requested range, off the interval grid, with another snapshot id or
another bar type than requested is refused with ``ValueError``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import in_window, splits
from lab.data import catalog
from lab.data.external import HoldoutWindowError, holdout_cut
from lab.runner.interface import BAR_COLUMNS, validate_bars

ASSETS = ("BTC", "ETH")
FIELDS = tuple(BAR_COLUMNS)
SOURCES = {"KRAKEN": "kraken", "BINANCE": "binance"}
STEPS = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1)}
ATTR_KEYS = ("snapshot_id", "instruments", "bar_type", "alignment")
ALIGNMENT_RULE = (
    "inner join on bar close time: a close is kept only where both BTC and ETH have a bar; "
    "no price is invented, interpolated or forward-filled"
)


def instruments(source: str) -> dict[str, str]:
    """``{"BTC": instrument id, "ETH": instrument id}`` of ``source`` (``"KRAKEN"`` or ``"BINANCE"``)."""
    if not isinstance(source, str) or source not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}, got {source!r}")
    return {asset: catalog.INSTRUMENTS[(SOURCES[source], asset)][0] for asset in ASSETS}


def _utc(value, name: str) -> pd.Timestamp:
    """``value`` as a UTC timestamp (naive means UTC); ``None`` or NaT raises."""
    ts = None if value is None else pd.Timestamp(value)
    if ts is None or ts is pd.NaT:
        raise ValueError(f"{name} must be a timestamp, got {value!r}")
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _isos(index: pd.DatetimeIndex) -> list[str]:
    return [ts.isoformat() for ts in index]


def _checked(
    frame,
    asset: str,
    expected: dict,
    lo: pd.Timestamp,
    hi: pd.Timestamp,
    step: pd.Timedelta,
    cut: pd.Timestamp,
) -> pd.DataFrame:
    """One asset's bars from the loader, refused unless they are what was requested (test window first)."""
    index = getattr(frame, "index", None)
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise ValueError(f"{asset}: the loader must return bars indexed by tz-aware close times")
    if len(index) and index.max() > cut:
        raise HoldoutWindowError(
            f"{asset}: data reach {index.max().tz_convert('UTC').isoformat()}, after {cut.isoformat()} "
            "(the test window)"
        )
    validate_bars(frame)
    if index[0] < lo or index[-1] > hi:
        raise ValueError(
            f"{asset}: the loader returned closes {index[0].isoformat()} .. {index[-1].isoformat()} outside the "
            f"requested {lo.isoformat()} .. {hi.isoformat()}"
        )
    ns = np.asarray(index.as_unit("ns").asi8, dtype=np.int64)
    off = int((ns % step.value != 0).sum())
    if off:
        raise ValueError(f"{asset}: {off} bar(s) close off the {step} grid")
    attrs = frame.attrs
    sid = attrs.get("snapshot_id")
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"{asset}: the loader's bars carry no snapshot_id")
    for key in ("instrument", "bar_type"):
        if key in attrs and attrs[key] != expected[key]:
            raise ValueError(
                f"{asset}: asked for {key} {expected[key]!r}, the loader returned {attrs[key]!r}"
            )
    out = pd.DataFrame(
        {f: frame[f].to_numpy(dtype=np.float64) for f in FIELDS},
        index=pd.DatetimeIndex(index.tz_convert("UTC").as_unit("us"), name="ts", freq=None),
    )
    out.attrs = {"snapshot_id": sid}
    return out


def load_panel(
    source: str = "KRAKEN",
    interval: str = "1d",
    start=None,
    *,
    last_close,
    catalog_dir: str | Path = "data/catalog",
    config_dir: Path | None = None,
    loader: Callable | None = None,
) -> pd.DataFrame:
    """BTC and ETH bars of ``source`` and ``interval`` as one panel (module docstring for the format and rules).

    ``start`` (inclusive, default: the start of train) and ``last_close`` (inclusive, required, at most the last
    validate close) bound the bar CLOSE times; naive means UTC. ``loader(instrument, interval, start=, end=,
    catalog_dir=)`` defaults to :func:`lab.data.catalog.load_bars`; it is called once per asset with
    ``end = last_close``. Raises :class:`HoldoutWindowError` for a request or returned data after the last
    validate close, ``ValueError`` for a bad source, interval or range, a loader breaking the request, or
    fewer than 2 common closes.
    """
    ids = instruments(source)
    if interval not in STEPS:
        raise ValueError(f"interval must be one of {sorted(STEPS)}, got {interval!r}")
    cut = holdout_cut(config_dir)
    end = _utc(last_close, "last_close")
    if end > cut:
        raise HoldoutWindowError(
            f"last_close {end.isoformat()} is after {cut.isoformat()}, the close of the last validate bar (the "
            "test window is opened once per strategy by the backtest-auditor, never through this loader)"
        )
    sp = splits(config_dir)
    first = _utc(start, "start") if start is not None else None
    lo = sp["train"][0] if first is None else max(first, sp["train"][0])
    if lo > end:
        raise ValueError(f"start {lo.isoformat()} is after last_close {end.isoformat()}")
    if loader is None:
        loader = catalog.load_bars
    step = STEPS[interval]

    blocks: dict[str, pd.DataFrame] = {}
    bar_types: dict[str, str] = {}
    for asset in ASSETS:
        bar_types[asset] = catalog.bar_type(ids[asset], interval)
        raw = loader(ids[asset], interval, start=lo, end=end, catalog_dir=catalog_dir)
        frame = _checked(
            raw, asset, {"instrument": ids[asset], "bar_type": bar_types[asset]}, lo, end, step, cut
        )
        # every close is in [lo, end] (checked), so only the window rule can still drop a bar
        keep = in_window(frame.index, sp["train"]) | in_window(frame.index, sp["validate"])
        blocks[asset] = frame.loc[keep]
    sids = {blocks[a].attrs["snapshot_id"] for a in ASSETS}
    if len(sids) != 1:
        raise ValueError(f"BTC and ETH bars come from different snapshots: {sorted(sids)}")

    present = {a: blocks[a].index for a in ASSETS}
    both = {a: present[a].isin(present[b]) for a, b in zip(ASSETS, ASSETS[::-1], strict=True)}
    aligned = {a: blocks[a].loc[both[a]] for a in ASSETS}
    index = aligned["BTC"].index
    assert index.equals(aligned["ETH"].index), "the two assets' common closes differ"
    if len(index) < 2:
        raise ValueError(
            f"{source} {interval}: fewer than 2 closes where both BTC and ETH have a bar between "
            f"{lo.isoformat()} and {end.isoformat()}"
        )
    for asset in ASSETS:
        validate_bars(aligned[asset])

    columns = pd.MultiIndex.from_product([ASSETS, FIELDS], names=["asset", "field"])
    values = np.column_stack([aligned[a][f].to_numpy(dtype=np.float64) for a in ASSETS for f in FIELDS])
    panel = pd.DataFrame(values, index=index, columns=columns)
    grid = pd.date_range(index[0], index[-1], freq=step, unit="us")
    missing = grid[~grid.isin(index)]
    panel.attrs = {
        "snapshot_id": sids.pop(),
        "instruments": dict(ids),
        "bar_type": bar_types,
        "alignment": {
            "rule": ALIGNMENT_RULE,
            "request": {"start": None if first is None else first.isoformat(), "last_close": end.isoformat()},
            "rows": {a: len(blocks[a]) for a in ASSETS},
            "common": len(index),
            "first": index[0].isoformat(),
            "last": index[-1].isoformat(),
            "dropped": {
                a: {"count": int((~both[a]).sum()), "closes": _isos(present[a][~both[a]])} for a in ASSETS
            },
            "missing": {"count": len(missing), "closes": _isos(missing)},
        },
    }
    return panel
