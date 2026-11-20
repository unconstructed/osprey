"""Binance USD-M futures positioning files from data.binance.vision: parse, normalise and check.

Files (downloaded by :func:`lab.data.sources.download_binance_futures`, one CSV member per zip):

- ``<SYM>-fundingRate-<YYYY-MM>.zip``: ``calc_time,funding_interval_hours,last_funding_rate``. ``calc_time`` is
  the funding instant in epoch ms (in the real files 0 to 47 ms after the hour; BTCUSDT and ETHUSDT fund every
  8 hours at 00, 08 and 16 UTC).
- ``<SYM>-metrics-<YYYY-MM-DD>.zip``: one row per 5 minutes, ``create_time`` as ``YYYY-MM-DD HH:MM:SS`` (UTC),
  ``symbol``, then six values (renamed here, :data:`METRIC_FIELDS`): open interest in contracts (= base units)
  and in USDT, the top traders' long/short ratio by accounts and by positions, the long/short ratio of all
  accounts, and the taker buy/sell volume ratio of the 5 minutes. Real files repeat rows, are not always in time
  order, and have empty fields (``""``), ``0E-8`` placeholders, and stretches where the feed froze (:func:`mark_stale`).
- ``<SYM>-5m-<YYYY-MM>.zip``: 5-minute futures klines (the spot kline layout, header optional), used only by
  :func:`metrics_timing`.

Cleaning: a zip must hold exactly one member named like the zip; a header line must be exactly the expected
one; a line with another number of fields is bad. Rows whose timestamp is invalid (or, in metrics, whose symbol
differs or whose six values are all missing) are dropped and counted. A single metrics value that is empty
(``missing_<field>``) or not a positive number (``invalid_<field>``, e.g. ``0E-8``) becomes NaN and is counted;
the row stays. :func:`mark_stale` then sets values of a frozen feed to NaN (causally) and lists them.
Rows are sorted by time (stable); duplicate timestamps keep the LAST row, and are counted as exact (every value
equal) or conflicting. Nothing is ever filled.

When is a value KNOWN (point in time; ``known_at``)?

- Funding rate: at ``calc_time``, the instant the rate is fixed and paid.
- Metrics: at ``create_time + 5 minutes`` (:data:`METRICS_LAG`). The 5-minute klines show that ``create_time``
  is the END of the 5-minute period in the older files and its START in the newer ones (the switch is in
  April 2024; :func:`metrics_timing` finds it per day), so the row's data can reach 5 minutes past its stamp.
  The build stops if any day's data reaches further than that.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.loaders import epoch_to_ns

FUNDING_HEADER = ("calc_time", "funding_interval_hours", "last_funding_rate")
METRICS_HEADER = (
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
KLINE_HEADER = (
    "open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
)
# metrics column in the file -> name in the lab
METRIC_FIELDS = {
    "sum_open_interest": "open_interest",
    "sum_open_interest_value": "open_interest_value",
    "count_toptrader_long_short_ratio": "top_account_ls_ratio",
    "sum_toptrader_long_short_ratio": "top_position_ls_ratio",
    "count_long_short_ratio": "account_ls_ratio",
    "sum_taker_long_short_vol_ratio": "taker_buy_sell_ratio",
}
METRICS_STEP = pd.Timedelta(minutes=5)
METRICS_LAG = pd.Timedelta(minutes=5)
FUNDING_LAG = pd.Timedelta(0)
STALE_AFTER = pd.Timedelta(hours=1)
CREATE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TOP = 10


def describe(td: pd.Timedelta) -> str:
    """A duration for people: ``"5 min"``, ``"1 h"``, ``"0 min"``."""
    minutes = int(td / pd.Timedelta(minutes=1))
    return f"{minutes // 60} h" if minutes and minutes % 60 == 0 else f"{minutes} min"


# --------------------------------------------------------------------------- reading


def read_zip_rows(path: str | Path, header: Sequence[str]) -> tuple[pd.DataFrame, dict]:
    """Every data line of the single CSV member of ``path`` as strings in the ``header`` columns.

    The member must be named like the zip (``X.zip`` holds ``X.csv``). A first line equal to ``header`` is
    skipped; a first line that starts with ``header[0]`` but differs is another layout and raises ``ValueError``.
    Lines with another number of fields are dropped and counted (``bad_width``). Quotes around a field are
    removed, so ``""`` is an empty field. Returns the rows and ``{"rows_read", "bad_width"}``.
    """
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        names = [i.filename for i in zf.infolist()]
        if names != [path.stem + ".csv"]:
            raise ValueError(f"{path.name}: expected one member {path.stem}.csv, found {names}")
        text = zf.read(names[0]).decode("utf-8")
    lines = [line.strip() for line in io.StringIO(text) if line.strip()]
    if lines and lines[0].split(",")[0].strip('"') == header[0]:
        if tuple(f.strip('"') for f in lines[0].split(",")) != tuple(header):
            raise ValueError(f"{path.name}: unexpected header {lines[0][:200]!r}")
        lines = lines[1:]
    fields = [[f.strip('"') for f in line.split(",")] for line in lines]
    good = [f for f in fields if len(f) == len(header)]
    frame = pd.DataFrame(good, columns=list(header), dtype=object)
    return frame, {"rows_read": len(fields), "bad_width": len(fields) - len(good)}


def _period_of(path: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end) of the UTC day or month in a file name ending ``-YYYY-MM-DD`` or ``-YYYY-MM``."""
    parts = path.stem.split("-")
    if len(parts[-3]) == 4 and parts[-3].isdigit():
        start = pd.Timestamp("-".join(parts[-3:]), tz="UTC")
        return start, start + pd.Timedelta(days=1)
    start = pd.Timestamp("-".join(parts[-2:]) + "-01", tz="UTC")
    return start, start + pd.offsets.MonthBegin(1)


def _to_utc(ns: pd.Series) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(ns.to_numpy(dtype="int64"), unit="ns", utc=True)).as_unit("us")


def _finish(frames: list[pd.DataFrame], counts: dict, value_cols: list[str]) -> pd.DataFrame:
    """Concatenate per-file frames (column ``ts`` + values), sort stably, keep the last row per ``ts``."""
    table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts", *value_cols])
    if table.empty:
        raise ValueError("no valid rows")
    table = table.iloc[np.argsort(table["ts"].to_numpy(), kind="stable")].reset_index(drop=True)
    dup = table["ts"].duplicated(keep="last").to_numpy()
    values = table[value_cols].to_numpy(dtype=float)
    later = np.flatnonzero(dup) + 1  # in a sorted table a duplicate's next row has the same ts
    same = (values[dup] == values[later]) | (np.isnan(values[dup]) & np.isnan(values[later]))
    counts["exact_duplicates"] = int(same.all(axis=1).sum())
    counts["conflicting_duplicates"] = int((~same.all(axis=1)).sum())
    counts["conflicting_examples"] = [t.isoformat() for t in table["ts"][dup][~same.all(axis=1)][:TOP]]
    table = table.loc[~dup].reset_index(drop=True)
    table["ts"] = pd.DatetimeIndex(table["ts"]).as_unit("us")
    table.attrs = counts
    return table


def _new_counts(paths: Sequence[Path]) -> dict:
    return {"files": len(paths), "rows_read": 0, "dropped_bad": 0, "files_out_of_order": 0,
            "rows_outside_file_period": 0}


def _tally(counts: dict, path: Path, info: dict, ts: pd.DatetimeIndex, bad: int) -> None:
    counts["rows_read"] += info["rows_read"]
    counts["dropped_bad"] += info["bad_width"] + bad
    counts["files_out_of_order"] += int(not ts.is_monotonic_increasing)
    lo, hi = _period_of(path)
    counts["rows_outside_file_period"] += int(((ts < lo) | (ts >= hi)).sum())


def load_funding(paths: Sequence[str | Path]) -> pd.DataFrame:
    """Funding-rate files -> ``ts`` (funding instant, UTC), ``rate`` (per funding interval, a fraction) and
    ``interval_hours``. A row is bad when ``calc_time`` is not an epoch integer, the rate is not finite or the
    interval is not a positive number. ``attrs``: counts (module docstring)."""
    paths = [Path(p) for p in paths]
    counts, frames = _new_counts(paths), []
    for path in paths:
        raw, info = read_zip_rows(path, FUNDING_HEADER)
        ns = epoch_to_ns(raw["calc_time"])
        rate = pd.to_numeric(raw["last_funding_rate"], errors="coerce").astype(float)
        hours = pd.to_numeric(raw["funding_interval_hours"], errors="coerce").astype(float)
        good = (ns.notna() & np.isfinite(rate) & (hours > 0) & np.isfinite(hours)).to_numpy(dtype=bool)
        ts = _to_utc(ns[good])
        _tally(counts, path, info, ts, int((~good).sum()))
        frames.append(pd.DataFrame({"ts": ts, "rate": rate[good].to_numpy(), "interval_hours": hours[good].to_numpy()}))
    return _finish(frames, counts, ["rate", "interval_hours"])


def load_metrics(paths: Sequence[str | Path], symbol: str) -> pd.DataFrame:
    """Metrics files of ``symbol`` -> ``ts`` (``create_time``, UTC) and the six :data:`METRIC_FIELDS` values.

    A row is bad when ``create_time`` is not ``YYYY-MM-DD HH:MM:SS``, its symbol is not ``symbol``, or none of
    its six values is a positive number. ``attrs``: the counts of the module docstring, plus
    ``missing_<field>`` and ``invalid_<field>`` per value column (counted on the rows kept as valid).
    """
    paths = [Path(p) for p in paths]
    counts, frames = _new_counts(paths), []
    names = list(METRIC_FIELDS.values())
    for name in names:
        counts[f"missing_{name}"] = counts[f"invalid_{name}"] = 0
    for path in paths:
        raw, info = read_zip_rows(path, METRICS_HEADER)
        ts = pd.to_datetime(raw["create_time"], format=CREATE_TIME_FORMAT, utc=True, errors="coerce")
        empty = pd.DataFrame({new: raw[old].eq("").to_numpy() for old, new in METRIC_FIELDS.items()})
        values = pd.DataFrame({new: pd.to_numeric(raw[old], errors="coerce").astype(float).to_numpy()
                               for old, new in METRIC_FIELDS.items()})
        values = values.where(np.isfinite(values) & (values > 0))  # a count or ratio must be a positive number
        good = (ts.notna() & raw["symbol"].eq(symbol)).to_numpy(dtype=bool) & values.notna().any(axis=1).to_numpy()
        for name in names:
            counts[f"missing_{name}"] += int((empty[name].to_numpy() & good).sum())
            counts[f"invalid_{name}"] += int((values[name].isna().to_numpy() & ~empty[name].to_numpy() & good).sum())
        stamps = pd.DatetimeIndex(ts[good]).as_unit("us")
        _tally(counts, path, info, stamps, int((~good).sum()))
        frames.append(pd.concat([pd.DataFrame({"ts": stamps}), values.loc[good].reset_index(drop=True)], axis=1))
    return _finish(frames, counts, names)


def load_klines_5m(paths: Sequence[str | Path]) -> pd.DataFrame:
    """5-minute futures klines -> ``ts`` (period START, UTC), ``open``, ``close``, ``volume`` and
    ``taker_buy_volume``, for :func:`metrics_timing` only. Bad: an invalid ``open_time``, a price that is not
    positive, a negative volume or a taker volume outside ``[0, volume]``."""
    paths = [Path(p) for p in paths]
    counts, frames = _new_counts(paths), []
    cols = ["open", "close", "volume", "taker_buy_volume"]
    for path in paths:
        raw, info = read_zip_rows(path, KLINE_HEADER)
        ns = epoch_to_ns(raw["open_time"])
        v = pd.DataFrame({c: pd.to_numeric(raw[c], errors="coerce").astype(float) for c in cols})
        good = ns.notna() & (v["open"] > 0) & (v["close"] > 0) & (v["volume"] >= 0)
        good &= (v["taker_buy_volume"] >= 0) & (v["taker_buy_volume"] <= v["volume"])
        good = good.to_numpy(dtype=bool)
        ts = _to_utc(ns[good])
        _tally(counts, path, info, ts, int((~good).sum()))
        frames.append(pd.concat([pd.DataFrame({"ts": ts}), v.loc[good].reset_index(drop=True)], axis=1))
    return _finish(frames, counts, cols)


def mark_stale(table: pd.DataFrame, after: pd.Timedelta = STALE_AFTER) -> tuple[pd.DataFrame, dict]:
    """Frozen-feed rule for metrics, applied per value column and causally.

    A run is a stretch of consecutive rows with the same value (a NaN ends a run). A value whose run started at
    least ``after`` earlier is set to NaN: from the moment the value has been unchanged for ``after``, never
    before, because at the time of the run's earlier rows the freeze could not be known yet (marking them would
    put the future into the data). In the real files open interest and the long/short ratios freeze together
    for up to 16 hours (BTCUSDT 2021-05-21/22), while a live market moves them every 5 minutes.
    ``open_interest_value`` is also set to NaN wherever ``open_interest`` is NaN (it is open interest times a
    price). Returns the table and ``{"stale_rows": {field: n}, "stale_runs": [...], "value_without_open_interest"}``.
    """
    out = table.copy()
    ts = pd.DatetimeIndex(out["ts"])
    ns = np.asarray(ts.as_unit("ns").asi8, dtype=np.int64)
    report: dict = {"after": describe(after), "stale_rows": {}, "stale_runs": []}
    for name in METRIC_FIELDS.values():
        v = out[name].to_numpy(dtype=float)
        change = np.concatenate([[True], ~(v[1:] == v[:-1])])
        run_start = ns[np.flatnonzero(change)][np.cumsum(change) - 1]
        stale = (ns - run_start >= after.value) & ~np.isnan(v)
        report["stale_rows"][name] = int(stale.sum())
        for a, b in _runs(stale):
            report["stale_runs"].append({"field": name, "from": _iso(ts[a]), "to": _iso(ts[b]), "rows": b - a + 1})
        out.loc[stale, name] = np.nan
    derived = (out["open_interest"].isna() & out["open_interest_value"].notna()).to_numpy()
    out.loc[derived, "open_interest_value"] = np.nan
    report["value_without_open_interest"] = int(derived.sum())
    out.attrs = dict(table.attrs)
    return out, report


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """(first, last) positions of every run of True."""
    padded = np.concatenate([[0], flags.astype(np.int8), [0]])
    edges = np.flatnonzero(np.diff(padded))
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2], strict=True)]


def with_known_at(table: pd.DataFrame, lag: pd.Timedelta, cut: pd.Timestamp) -> tuple[pd.DataFrame, int]:
    """Add ``known_at = ts + lag`` (second column) and keep only the rows known strictly before ``cut``.
    Returns the table and the number of rows dropped for being known at or after ``cut``."""
    out = table.copy()
    out.insert(1, "known_at", pd.DatetimeIndex(out["ts"] + lag).as_unit("us"))
    keep = (out["known_at"] < cut).to_numpy()
    out = out.loc[keep].reset_index(drop=True)
    out.attrs = dict(table.attrs)
    return out, int((~keep).sum())


# --------------------------------------------------------------------------- checks


def _iso(ts) -> str:
    return pd.Timestamp(ts).isoformat()


def _gaps(ts: pd.DatetimeIndex, step: np.ndarray) -> list[dict]:
    """Runs of missing events between consecutive times ``ts`` expected every ``step`` ns (per later event)."""
    ns = np.asarray(ts.as_unit("ns").asi8, dtype=np.int64)
    if len(ns) < 2:
        return []
    missing = np.rint(np.diff(ns) / step[1:]).astype(np.int64) - 1
    return [{"after": _iso(ts[i]), "before": _iso(ts[i + 1]), "missing": int(missing[i])}
            for i in np.flatnonzero(missing > 0)]


def _gap_summary(gaps: list[dict]) -> dict:
    return {"gaps": len(gaps), "missing": int(sum(g["missing"] for g in gaps)),
            "longest_gaps": sorted(gaps, key=lambda g: (-g["missing"], g["after"]))[:TOP]}


def check_funding(table: pd.DataFrame) -> dict:
    """Quality of one funding series: span, intervals, distance of each instant from its interval grid, missing
    funding events (gaps), and the extreme rates. JSON-ready."""
    ts = pd.DatetimeIndex(table["ts"])
    rate, hours = table["rate"].to_numpy(), table["interval_hours"].to_numpy()
    step = (hours * 3600e9).astype(np.int64)
    ns = np.asarray(ts.as_unit("ns").asi8, dtype=np.int64)
    offset = ns % step
    offset = np.where(offset > step // 2, offset - step, offset)  # signed distance from the nearest slot
    biggest = np.argsort(-np.abs(rate), kind="stable")[:5]
    return {
        "rows": len(table),
        "first": _iso(ts[0]),
        "last": _iso(ts[-1]),
        "interval_hours": {f"{h:g}": int(n) for h, n in zip(*np.unique(hours, return_counts=True), strict=True)},
        "grid_offset_ms": {"min": int(offset.min() // 1_000_000), "max": int(offset.max() // 1_000_000)},
        "off_grid_over_1min": int((np.abs(offset) > 60e9).sum()),
        **_gap_summary(_gaps(ts, step)),
        "rate": {"min": float(rate.min()), "p01": float(np.quantile(rate, 0.01)), "median": float(np.median(rate)),
                 "p99": float(np.quantile(rate, 0.99)), "max": float(rate.max())},
        "largest_abs": [{"ts": _iso(ts[i]), "rate": float(rate[i])} for i in biggest],
    }


def check_metrics(table: pd.DataFrame) -> dict:
    """Quality of one metrics series: span, the 5-minute grid (off-grid stamps, missing slots and gaps, days
    with fewer than 288 rows), per value: rows with a value and its longest absence, and for open interest the
    largest 5-minute moves and the longest run of an unchanged value. JSON-ready."""
    ts = pd.DatetimeIndex(table["ts"])
    ns = np.asarray(ts.as_unit("ns").asi8, dtype=np.int64)
    step = METRICS_STEP.value
    gaps = _gaps(ts, np.full(len(ts), step, dtype=np.int64))
    per_day = pd.Series(1, index=ts.floor("D")).groupby(level=0).sum()
    all_days = pd.date_range(ts[0].floor("D"), ts[-1].floor("D"), freq="D")
    per_day = per_day.reindex(all_days, fill_value=0)
    out = {
        "rows": len(table),
        "first": _iso(ts[0]),
        "last": _iso(ts[-1]),
        "expected_rows": int((ns[-1] - ns[0]) // step) + 1,
        "off_grid": int((ns % step != 0).sum()),
        **_gap_summary(gaps),
        "days": len(all_days),
        "days_short": int((per_day < 288).sum()),
        "days_empty": int((per_day == 0).sum()),
        "short_days": [{"day": d.date().isoformat(), "rows": int(n)} for d, n in per_day[per_day < 288].items()][:50],
        "fields": {},
    }
    for name in METRIC_FIELDS.values():
        have = table[name].notna().to_numpy()
        absent = _longest_run(~have)
        out["fields"][name] = {
            "rows": int(have.sum()),
            "first": _iso(ts[have][0]) if have.any() else None,
            "last": _iso(ts[have][-1]) if have.any() else None,
            "longest_absence": None if absent is None else
            {"from": _iso(ts[absent[0]]), "to": _iso(ts[absent[1]]), "rows": absent[1] - absent[0] + 1},
        }
    oi = table["open_interest"].to_numpy()
    with np.errstate(invalid="ignore"):
        move = np.abs(np.diff(np.log(oi), prepend=np.nan))
    order = np.argsort(-np.nan_to_num(move, nan=-1.0), kind="stable")[:5]
    out["open_interest_largest_moves"] = [
        {"ts": _iso(ts[i]), "abs_log_change": round(float(move[i]), 6)} for i in order if np.isfinite(move[i])
    ]
    stale = _longest_run(np.concatenate([[False], oi[1:] == oi[:-1]]))
    out["open_interest_longest_unchanged"] = None if stale is None else {
        "from": _iso(ts[stale[0] - 1]), "to": _iso(ts[stale[1]]), "rows": stale[1] - stale[0] + 2}
    return out


def _longest_run(flags: np.ndarray) -> tuple[int, int] | None:
    """(first, last) position of the longest run of True (the earliest one on ties), or None."""
    return max(_runs(flags), key=lambda r: (r[1] - r[0], -r[0]), default=None)


TAKER_OFFSETS = (-10, -5, 0, 5)  # minutes: kline period [T + k, T + k + 5) compared with the row stamped T
PRICE_OFFSETS = (-5, 0, 5, 10)  # minutes: price at T + k (the open of the kline starting then)
MIN_MATCHED = 100  # rows of a day that must be comparable for a verdict
CLEAR_WIN = 0.5  # the best offset's median error must be under this share of the second best


def _best(errors: dict[int, np.ndarray]) -> tuple[int | None, float | None, bool]:
    """(offset with the smallest median error, that median, whether it wins clearly) for one day."""
    medians = {k: float(np.median(e)) for k, e in errors.items() if len(e) >= MIN_MATCHED}
    if len(medians) < 2:
        return None, None, False
    ranked = sorted(medians, key=lambda k: (medians[k], abs(k)))
    first, second = medians[ranked[0]], medians[ranked[1]]
    return ranked[0], first, bool(first < CLEAR_WIN * second)


def metrics_timing(metrics: pd.DataFrame, klines: pd.DataFrame) -> dict:
    """Up to when does a metrics row stamped T describe the market? Checked per UTC day against 5m klines.

    - Taker ratio: the row's ``taker_buy_sell_ratio`` against ``taker_buy / (volume - taker_buy)`` of the kline
      period ``[T + k, T + k + 5 min)`` for ``k`` in :data:`TAKER_OFFSETS`; the data reach ``T + k + 5``.
    - Open interest: ``open_interest_value / open_interest`` (the price the value was taken at) against the
      price at ``T + k`` (open of the kline starting then) for ``k`` in :data:`PRICE_OFFSETS`; data reach ``T + k``.

    Per day and check, the offset with the smallest median relative error wins if at least ``MIN_MATCHED`` rows
    compare and it beats the runner-up clearly (``CLEAR_WIN``); else the check is inconclusive that day.
    ``reach_minutes`` is the latest point any conclusive check puts the day's data at, relative to T. Returns
    ``{"days": [...], "runs": [...], "max_reach_minutes", "inconclusive_days"}``, where ``runs`` groups
    consecutive days with the same verdicts.
    """
    ts = pd.DatetimeIndex(metrics["ts"])
    kl = klines.set_index(pd.DatetimeIndex(klines["ts"]))
    sell = kl["volume"] - kl["taker_buy_volume"]
    k_ratio = kl["taker_buy_volume"] / sell.where(sell > 0)
    taker = metrics["taker_buy_sell_ratio"].to_numpy()
    implied = (metrics["open_interest_value"] / metrics["open_interest"]).to_numpy()
    days_ns = np.asarray(ts.floor("D").as_unit("ns").asi8, dtype=np.int64)  # ts is sorted: each day is a slice
    starts = np.flatnonzero(np.concatenate([[True], days_ns[1:] != days_ns[:-1]]))
    bounds = zip(starts, np.append(starts[1:], len(ts)), strict=True)
    errors = {}
    for check, values, offsets, series in (("taker", taker, TAKER_OFFSETS, k_ratio),
                                           ("price", implied, PRICE_OFFSETS, kl["open"])):
        for k in offsets:
            ref = series.reindex(ts + pd.Timedelta(minutes=k)).to_numpy()
            with np.errstate(divide="ignore", invalid="ignore"):
                errors[(check, k)] = np.abs(values / ref - 1)
    days = []
    for lo, hi in bounds:
        rows = slice(lo, hi)
        record: dict = {"day": ts[lo].date().isoformat(), "rows": int(hi - lo)}
        reach = []
        for check, offsets, extra in (("taker", TAKER_OFFSETS, 5), ("price", PRICE_OFFSETS, 0)):
            per_k = {}
            for k in offsets:
                e = errors[(check, k)][rows]
                per_k[k] = e[np.isfinite(e)]
            best, err, clear = _best(per_k)
            record[check] = {"offset": best, "median_error": err, "conclusive": clear}
            if clear:
                reach.append(best + extra)
        record["reach_minutes"] = max(reach) if reach else None
        days.append(record)
    runs: list[dict] = []
    for r in days:
        key = (r["taker"]["offset"] if r["taker"]["conclusive"] else None,
               r["price"]["offset"] if r["price"]["conclusive"] else None)
        if runs and runs[-1]["_key"] == key:
            runs[-1]["to"], runs[-1]["days"] = r["day"], runs[-1]["days"] + 1
        else:
            runs.append({"_key": key, "from": r["day"], "to": r["day"], "days": 1,
                         "taker_offset": key[0], "price_offset": key[1]})
    for run in runs:
        del run["_key"]
    reached = [r["reach_minutes"] for r in days if r["reach_minutes"] is not None]
    return {
        "days": days,
        "runs": runs,
        "max_reach_minutes": max(reached) if reached else None,
        "inconclusive_days": sum(r["reach_minutes"] is None for r in days),
    }
