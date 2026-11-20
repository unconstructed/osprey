"""Build the data catalog: download, normalise, check, write the Nautilus catalog, SNAPSHOT.json and the report.

    uv run python -m lab.data.build --sources kraken,binance            # the AGENTS.md command
    uv run python -m lab.data.build                                     # kraken, binance and coinbase
    uv run python -m lab.data.build --offline                           # rebuild from data/raw, no network
    uv run python -m lab.data.build --sources kraken,binance,coinbase,binance_futures   # plus positioning data

Steps (AGENTS.md "Data" pipeline):

1. Raw files into ``<data>/raw/<source>/`` with a SHA-256 of each (:mod:`lab.data.sources`).
2. Normalise to the standard bars (:mod:`lab.data.loaders`): UTC close-time index, OHLCV float64, bad rows
   dropped and counted, duplicates resolved. Binance bars go through the loader's grid mode (bars cut short
   by maintenance keep their interval; bars whose open is off the grid are dropped and listed). Zero-volume
   bars are dropped and listed: they are exchange placeholders for intervals without trades (Kraken omits
   such intervals), and a backtest must not fill an order on a halted exchange. Gaps are never filled.
3. Quality checks (:mod:`lab.data.quality`): per series; daily vs hourly of the same source; the same-day
   close across sources (tolerance ``--tolerance``, default 1%); coverage of the train window; every pair of
   sources must agree best with no time shift, else the build stops.
4. Instruments and bars into a Nautilus ``ParquetDataCatalog`` (:mod:`lab.data.catalog`), built in a staging
   directory, read back with ``load_bars`` and compared with what was written (round trip).
5. ``SNAPSHOT.json``. The snapshot ID is the first 16 hex characters of the SHA-256 of the sorted raw-file
   SHA-256 hex digests joined by newlines, so a changed raw file means a new ID. A snapshot is never
   overwritten in place: a new ID moves the current catalog to ``<data>/snapshots/<old id>/`` first; the same
   ID with identical bars (``content_sha256``) keeps the existing catalog; the same ID with different bars
   (a code change) stops with an error.
6. The data quality report ``<report-dir>/<YYYY-MM-DD>.md`` (:mod:`lab.data.report`; a report of another
   snapshot with that name is never overwritten: the new one gets ``-<snapshot id>`` added).

With ``binance_futures`` among the sources (opt-in; it needs at least one bar source) the same snapshot also
holds Binance USD-M futures positioning data (:mod:`lab.data.futures`, :mod:`lab.data.external`): funding
rates, open interest and long/short ratios for BTCUSDT and ETHUSDT, downloaded only up to the last day of the
validate window, checked (including when each value became known, against 5-minute futures klines; the build
stops if a metrics row's data reach further past its stamp than the ``known_at`` lag), stored under
``<catalog>/ext/`` with ``known_at`` per row, read back and compared, and described in
``<report-dir>/<YYYY-MM-DD>-positioning.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import combinations
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from lab.config import REPO_ROOT, splits
from lab.data import catalog as cat
from lab.data import external as ext
from lab.data import futures as fu
from lab.data import quality
from lab.data import sources as src
from lab.data.loaders import load_binance_klines, load_coinbase_candles, load_kraken_ohlcvt
from lab.data.report import write_positioning_report, write_report

log = logging.getLogger("lab.data.build")

SOURCES = ("kraken", "binance", "coinbase")  # bar sources; the default
EXT_SOURCES = ("binance_futures",)  # positioning data; opt-in
ALL_SOURCES = SOURCES + EXT_SOURCES
SCHEMA = "osprey.snapshot/1"
ID_RULE = "first 16 hex of sha256 over the sorted raw-file sha256 hex digests joined by '\\n'"
STAGING = "catalog.staging"


class DataQualityError(RuntimeError):
    """A check that must hold for the data to be usable failed (e.g. two sources on different clocks)."""


class SnapshotConflict(RuntimeError):
    """The same snapshot ID would get different bars: refuse to overwrite a snapshot in place."""


@dataclass
class BuildConfig:
    sources: tuple[str, ...] = SOURCES
    coins: tuple[str, ...] = src.COINS
    intervals: tuple[str, ...] = src.INTERVALS
    data_dir: Path = Path("data")
    report_dir: Path | None = Path("reports/data")
    offline: bool = False
    tolerance: float = 0.01


@dataclass
class Series:
    """One normalised series and what loading and the build's policy removed from it."""

    source: str
    coin: str
    interval: str
    bars: pd.DataFrame
    loading: dict = field(default_factory=dict)

    @property
    def instrument(self) -> str:
        return cat.INSTRUMENTS[(self.source, self.coin)][0]

    @property
    def bar_type(self) -> str:
        return cat.bar_type(self.instrument, self.interval)


def _csv(text: str, allowed: tuple[str, ...], what: str) -> tuple[str, ...]:
    items = tuple(dict.fromkeys(x.strip() for x in text.split(",") if x.strip()))
    bad = [x for x in items if x not in allowed]
    if bad or not items:
        raise argparse.ArgumentTypeError(f"{what} must be a comma list from {','.join(allowed)}; got {text!r}")
    return items


def parse_args(argv: list[str] | None = None) -> BuildConfig:
    p = argparse.ArgumentParser(prog="python -m lab.data.build", description=__doc__.split("\n\n")[0])
    p.add_argument("--sources", default=",".join(SOURCES), type=lambda s: _csv(s, ALL_SOURCES, "--sources"))
    p.add_argument("--coins", default=",".join(src.COINS), type=lambda s: _csv(s, src.COINS, "--coins"))
    p.add_argument(
        "--intervals", default=",".join(src.INTERVALS), type=lambda s: _csv(s, src.INTERVALS, "--intervals")
    )
    p.add_argument("--data-dir", default="data", type=Path)
    p.add_argument("--report-dir", default="reports/data", help="'' to skip the report")
    p.add_argument("--offline", action="store_true", help="rebuild from <data-dir>/raw without network")
    p.add_argument("--tolerance", default=0.01, type=float, help="cross-check tolerance (default 0.01 = 1%%)")
    a = p.parse_args(argv)
    if not a.tolerance > 0:
        p.error("--tolerance must be positive")
    if not set(a.sources) & set(SOURCES):
        p.error(f"--sources needs at least one bar source ({','.join(SOURCES)})")
    return BuildConfig(
        sources=a.sources,
        coins=a.coins,
        intervals=a.intervals,
        data_dir=a.data_dir,
        report_dir=Path(a.report_dir) if a.report_dir else None,  # Path("") would be "." and write here
        offline=a.offline,
        tolerance=a.tolerance,
    )


# --------------------------------------------------------------------------- 1. raw files


def collect(cfg: BuildConfig, client: httpx.Client | None, now: datetime) -> dict[str, src.SourceFiles]:
    """Download (or, with ``client=None``, find and verify on disk) every selected source."""
    raw = cfg.data_dir / "raw"
    out = {}
    for name in cfg.sources:
        log.info("%s: %s", name, "verifying files on disk" if client is None else "downloading")
        if name == "kraken":
            out[name] = src.download_kraken(client, raw / "kraken", cfg.coins, cfg.intervals, now=now)
        elif name == "binance":
            out[name] = src.download_binance(client, raw / "binance", cfg.coins, cfg.intervals, now=now)
        elif name == "binance_futures":
            out[name] = src.download_binance_futures(
                client, raw / "binance_futures", cfg.coins, last_day=ext_last_day(now)
            )
        else:
            out[name] = src.download_coinbase(client, raw / "coinbase", cfg.coins, now=now)
    return out


def ext_last_day(now: datetime) -> date:
    """Last day of positioning files to download: the validate window's last day (config/splits.yaml), or the
    day before ``now`` if that is earlier. Nothing of the test window is ever requested."""
    return min(splits()["validate"][1].date(), (now.astimezone(UTC) - timedelta(days=1)).date())


def compute_snapshot_id(hashes) -> str:
    """See ``ID_RULE``."""
    return hashlib.sha256("\n".join(sorted(hashes)).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- 2. normalise


def _combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Monthly frames -> one series: sorted, duplicates across files keep the last; loader counts summed."""
    bars = pd.concat(frames)
    bars = bars.iloc[np.argsort(bars.index.asi8, kind="stable")]
    duplicate = bars.index.duplicated(keep="last")
    bars = bars.loc[~duplicate].copy()
    attrs = {"files": len(frames), "dropped_duplicates": int(duplicate.sum())}
    for key in ("rows_read", "dropped_bad", "dropped_duplicates", "dropped_off_grid"):
        attrs[key] = attrs.get(key, 0) + sum(f.attrs.get(key, 0) for f in frames)
    for key in ("off_grid_opens", "short_bars"):
        attrs[key] = [x for f in frames for x in f.attrs.get(key, [])]
    bars.attrs = attrs
    return bars


def normalise(files: dict[str, src.SourceFiles]) -> list[Series]:
    """Load every series with the source's loader, then drop zero-volume bars (listed, never filled)."""
    out = []
    for name, got in files.items():
        if name in EXT_SOURCES:
            continue  # normalise_external
        for (coin, interval), paths in sorted(got.series.items()):
            if name == "kraken":
                bars = load_kraken_ohlcvt(paths[0])
            elif name == "binance":
                bars = _combine([load_binance_klines(p, interval=quality.step_of(interval)) for p in paths])
            else:
                bars = load_coinbase_candles(paths)
            loading = {k: v for k, v in bars.attrs.items() if k != "source"}
            zero = (bars["volume"] == 0).to_numpy()
            loading["dropped_zero_volume"] = int(zero.sum())
            loading["zero_volume_bars"] = [quality.iso(t) for t in bars.index[zero]]
            bars = bars.loc[~zero, list(cat.BAR_COLUMNS)].copy()
            bars.attrs = {}
            out.append(Series(name, coin, interval, bars, loading))
    return out


@dataclass
class External:
    """One symbol's positioning tables as stored (``known_at`` added, cut at the holdout), what loading and
    cleaning removed, and the timing check of its metrics."""

    symbol: str
    funding: pd.DataFrame
    metrics: pd.DataFrame
    loading: dict
    timing: dict


def _ext_paths(got: src.SourceFiles, coin: str, kind: str) -> list[Path]:
    paths = got.series.get((coin, kind))
    if not paths:
        raise DataQualityError(f"{src.BINANCE_SYMBOLS[coin]}: no {kind} files; nothing to build positioning from")
    return paths


def normalise_external(got: src.SourceFiles, coins: tuple[str, ...], cut: pd.Timestamp) -> list[External]:
    """Load, clean and time-stamp (``known_at``) each coin's futures files; keep what is known before ``cut``.

    The timing check runs on the metrics as loaded (before the stale rule), against the 5-minute klines.
    """
    out = []
    for coin in coins:
        sym = src.BINANCE_SYMBOLS[coin]
        funding = fu.load_funding(_ext_paths(got, coin, "funding"))
        metrics = fu.load_metrics(_ext_paths(got, coin, "metrics"), sym)
        timing = fu.metrics_timing(metrics, fu.load_klines_5m(_ext_paths(got, coin, "klines_5m")))
        cleaned, stale = fu.mark_stale(metrics)
        funding_k, f_after = fu.with_known_at(funding, fu.FUNDING_LAG, cut)
        metrics_k, m_after = fu.with_known_at(cleaned, fu.METRICS_LAG, cut)
        loading = {
            "funding": {**funding.attrs, "dropped_known_at_or_after_cut": f_after},
            "metrics": {**metrics.attrs, **stale, "dropped_known_at_or_after_cut": m_after},
        }
        out.append(External(sym, funding_k, metrics_k, loading, timing))
    return out


def check_external(exts: list[External]) -> dict:
    """Quality of the stored positioning tables, the metrics timing summary (raises :class:`DataQualityError`
    when a day's data reach further past the stamp than ``futures.METRICS_LAG``), and how much of the train and
    validate windows' daily closes get a value from :func:`external.positioning_at`."""
    lag = fu.METRICS_LAG / pd.Timedelta(minutes=1)
    checks: dict = {"external": {}, "external_loading": {}, "metrics_timing": {}, "positioning_coverage": {}}
    windows = splits()
    for e in exts:
        reach = e.timing["max_reach_minutes"]
        if reach is not None and reach > lag:
            raise DataQualityError(
                f"{e.symbol}: on some days the metrics describe the market up to {reach} minutes after their "
                f"create_time, more than the {lag:g}-minute lag used for known_at (look-ahead); runs: "
                f"{e.timing['runs']}"
            )
        checks["metrics_timing"][e.symbol] = {k: v for k, v in e.timing.items() if k != "days"}
        checks["external"][f"{e.symbol} funding"] = fu.check_funding(e.funding)
        checks["external"][f"{e.symbol} metrics"] = fu.check_metrics(e.metrics)
        checks["external_loading"][e.symbol] = e.loading
        coverage = {}
        for name in ("train", "validate"):
            start, end = windows[name]
            closes = pd.date_range(start + pd.Timedelta(days=1), end + pd.Timedelta(days=1), freq="1D")
            rows = ext.positioning_at(e.funding, e.metrics, closes)
            columns = {}
            for col in ext.OUTPUT_COLUMNS:
                have = rows[col] > 0 if col.startswith("funding_count") else rows[col].notna()
                columns[col] = {"closes": int(have.sum()),
                                "first": quality.iso(rows.index[have.to_numpy()][0]) if have.any() else None}
            coverage[name] = {"closes": len(closes), "columns": columns}
        checks["positioning_coverage"][e.symbol] = coverage
    return checks


# --------------------------------------------------------------------------- 3. checks


def run_checks(series: list[Series], tolerance: float) -> dict:
    """Per-series quality, daily vs hourly per source and coin, cross-source closes per coin, train coverage,
    and the time alignment of every pair of sources (raises :class:`DataQualityError` if one is shifted)."""
    train = splits()["train"]
    by_key = {(s.source, s.coin, s.interval): s for s in series}
    checks: dict = {"quality": {}, "loading": {}, "train_coverage": {}, "daily_vs_hourly": {}, "cross_check": {}}
    for s in series:
        checks["quality"][s.bar_type] = quality.check_series(s.bars, s.interval)
        checks["loading"][s.bar_type] = s.loading
        checks["train_coverage"][s.bar_type] = quality.window_coverage(s.bars.index, s.interval, train)
    for (source, coin, interval), s in by_key.items():
        hourly = by_key.get((source, coin, "1h"))
        if interval == "1d" and hourly is not None:
            checks["daily_vs_hourly"][s.instrument] = quality.compare_intervals(s.bars, hourly.bars)
    checks["alignment"] = {}
    for coin in sorted({s.coin for s in series}):
        hourly = {s.source: s.bars.index for s in series if s.coin == coin and s.interval == "1h"}
        closes = {s.source: s.bars["close"] for s in series if s.coin == coin and s.interval == "1d"}
        if len(closes) >= 2:
            checks["cross_check"][coin] = quality.cross_check(closes, tolerance, hourly)
        for interval in quality.INTERVALS:
            have = {s.source: s.bars["close"] for s in series if s.coin == coin and s.interval == interval}
            for a, b in combinations(sorted(have), 2):
                result = quality.lag_alignment(have[a], have[b], quality.step_of(interval))
                checks["alignment"].setdefault(coin, {}).setdefault(interval, {})[f"{a}/{b}"] = result
                if not result["aligned"]:
                    raise DataQualityError(
                        f"{coin} {interval}: {a} and {b} agree best when shifted by {result['best_lag']} bars "
                        f"(median |log ratio| by shift: {result['median_abs_log_diff']}); a time-zone or "
                        "labelling error in one of them"
                    )
    return checks


# --------------------------------------------------------------------------- 4-5. catalog and snapshot


def git_state(repo: Path = REPO_ROOT) -> dict:
    """Commit of the code that built the catalog and whether ``lab/`` had uncommitted or untracked changes."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    if head.returncode != 0:
        return {"commit": "unknown", "lab_dirty": None}
    status = subprocess.run(["git", "status", "--porcelain", "--", "lab"], cwd=repo, capture_output=True, text=True)
    return {"commit": head.stdout.strip(), "lab_dirty": bool(status.stdout.strip())}


def content_hash(frames: dict[str, pd.DataFrame], tables: dict[str, pd.DataFrame] | None = None) -> str:
    """SHA-256 over every bar type (sorted) and its close-time ns and OHLCV float64 bytes as loaded back, then
    (when given) every stored positioning table (sorted by path): its times as ns and its values as float64.
    Without ``tables`` the hash is the bars-only hash of earlier snapshots."""
    digest = hashlib.sha256()
    for bt in sorted(frames):
        f = frames[bt]
        digest.update(bt.encode())
        digest.update(np.asarray(f.index.as_unit("ns").asi8, dtype="<i8").tobytes())
        digest.update(np.ascontiguousarray(f.loc[:, list(cat.BAR_COLUMNS)].to_numpy(dtype="<f8")).tobytes())
    for path in sorted(tables or {}):
        digest.update(path.encode())
        for col, values in tables[path].items():
            digest.update(col.encode())
            if col in ("ts", "known_at"):
                digest.update(np.asarray(pd.DatetimeIndex(values).as_unit("ns").asi8, dtype="<i8").tobytes())
            else:
                digest.update(np.ascontiguousarray(values.to_numpy(dtype="<f8")).tobytes())
    return digest.hexdigest()


def _ulps(got: np.ndarray, source: np.ndarray) -> float:
    return float(np.max(np.abs(got - source) / np.spacing(np.abs(source)))) if len(source) else 0.0


def write_staging(staging: Path, series: list[Series], snapshot: dict, exts: list[External] = ()) -> dict:
    """Write instruments, bars, the positioning tables of ``exts`` and SNAPSHOT.json into ``staging``; read
    every series back with ``load_bars`` and every table with ``external.read_table``.

    Returns the snapshot with ``series``, ``content_sha256`` and (with ``exts``) ``external`` filled in. The
    bar round trip must be exact against :func:`catalog.stored_values`; the distance from the source floats is
    recorded (prices: ulps, volumes: absolute rounding at 1e-8). Tables must come back equal.
    """
    if staging.exists():
        shutil.rmtree(staging)  # left over from an interrupted build; it was never published
    pairs = sorted({(s.source, s.coin) for s in series})
    precision = {p: cat.price_precision(*[s.bars for s in series if (s.source, s.coin) == p]) for p in pairs}
    instruments = [cat.make_instrument(*cat.INSTRUMENTS[p], precision[p]) for p in pairs]
    cat.write_catalog(
        staging,
        instruments,
        {s.bar_type: cat.to_nautilus(s.bars, s.bar_type, precision[(s.source, s.coin)]) for s in series},
    )
    (staging / cat.SNAPSHOT_FILE).write_text(json.dumps(snapshot, indent=2, allow_nan=False))
    loaded, round_trip = {}, {}
    for s in series:
        p = precision[(s.source, s.coin)]
        got = cat.load_bars(s.instrument, s.interval, catalog_dir=staging)
        want = cat.stored_values(s.bars, p)
        exact = got.index.equals(s.bars.index) and got.loc[:, list(cat.BAR_COLUMNS)].equals(want)
        if not exact:
            raise RuntimeError(f"{s.bar_type}: catalog round trip differs from what was written")
        prices = list(cat.PRICE_COLUMNS)
        round_trip[s.bar_type] = {
            "exact": exact,
            "rows": len(got),
            "price_precision": p,
            "max_price_ulps_vs_source": _ulps(got[prices].to_numpy().ravel(), s.bars[prices].to_numpy().ravel()),
            "max_volume_rounding": float(np.max(np.abs(got["volume"].to_numpy() - s.bars["volume"].to_numpy()))),
        }
        loaded[s.bar_type] = got
    tables = {}
    for e in exts:
        for name, frame in (("funding", e.funding), ("metrics", e.metrics)):
            entry = ext.write_table(staging, e.symbol, name, frame)
            back = ext.read_table(staging, e.symbol, name, sha256=entry["sha256"])
            if not back.equals(frame):
                raise RuntimeError(f"{entry['path']}: round trip differs from what was written")
            snapshot.setdefault("external", []).append(entry)
            tables[entry["path"]] = back
    snapshot["content_sha256"] = content_hash(loaded, tables)
    snapshot["bars_content_sha256"] = content_hash(loaded)  # equal across snapshots whose bars are equal
    snapshot["series"] = [
        {
            "instrument": s.instrument,
            "source": s.source,
            "bar": s.interval,
            "bar_type": s.bar_type,
            "start": quality.iso(s.bars.index[0]),
            "end": quality.iso(s.bars.index[-1]),
            "rows": len(s.bars),
            "gaps": snapshot["checks"]["quality"][s.bar_type]["gaps"],
            "missing_bars": snapshot["checks"]["quality"][s.bar_type]["missing_bars"],
            "price_precision": precision[(s.source, s.coin)],
        }
        for s in series
    ]
    snapshot["checks"]["round_trip"] = round_trip
    (staging / cat.SNAPSHOT_FILE).write_text(json.dumps(snapshot, indent=2, allow_nan=False))
    return snapshot


def publish(staging: Path, catalog_dir: Path, archive_dir: Path) -> tuple[dict, str]:
    """Move ``staging`` into ``catalog_dir`` without ever overwriting a snapshot in place (module docstring).

    Returns the snapshot now in ``catalog_dir`` and what happened: "new", "unchanged" or "replaced <old id>".
    """
    new = json.loads((staging / cat.SNAPSHOT_FILE).read_text())
    if not catalog_dir.exists():
        staging.rename(catalog_dir)
        return new, "new"
    old_path = catalog_dir / cat.SNAPSHOT_FILE
    if not old_path.is_file():
        raise SnapshotConflict(f"{catalog_dir} exists without {cat.SNAPSHOT_FILE}; move it away first")
    old = json.loads(old_path.read_text())
    if old.get("snapshot_id") == new["snapshot_id"]:
        if old.get("content_sha256") != new["content_sha256"]:
            raise SnapshotConflict(
                f"snapshot {new['snapshot_id']}: same raw files but different bars (did the normalising code "
                f"change?). Refusing to overwrite it in place; move {catalog_dir} away to rebuild."
            )
        shutil.rmtree(staging)
        return old, "unchanged"
    target = archive_dir / str(old.get("snapshot_id"))
    if target.exists():
        raise SnapshotConflict(f"{target} already exists; refusing to overwrite an archived snapshot")
    archive_dir.mkdir(parents=True, exist_ok=True)
    catalog_dir.rename(target)
    staging.rename(catalog_dir)
    return new, f"replaced {old.get('snapshot_id')} (archived to {target})"


SOURCE_NOTES = {
    "kraken": "Kraken downloadable OHLCVT full history (official zip in parts); members read by HTTP range "
    "requests. Verified: member CRC-32 and size. NOT verified: the whole-archive SHA-256 (never held).",
    "binance": "data.binance.vision monthly spot klines (USDT quote); every zip verified against its "
    "published .CHECKSUM (SHA-256).",
    "coinbase": "Coinbase Exchange public REST daily candles (USD), raw JSON pages; for the cross-check only. "
    "No published checksums.",
    "binance_futures": "data.binance.vision USD-M futures (data/futures/um/): monthly funding rates, daily metrics "
    "(open interest, long/short ratios) and monthly 5-minute klines (only to check when metrics become known); "
    "every zip verified against its published .CHECKSUM (SHA-256). Nothing after the last day of the validate "
    "window is requested.",
}


def build(cfg: BuildConfig, client: httpx.Client | None = None, now: datetime | None = None) -> dict:
    """Run the whole pipeline (module docstring). Returns the published snapshot with ``"publish"`` and,
    when a report was written, ``"report"`` added (not stored in SNAPSHOT.json)."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    own = None
    if not cfg.offline and client is None:
        client = own = src.make_client()
    try:
        files = collect(cfg, None if cfg.offline else client, now)
    finally:
        if own is not None:
            own.close()
    series = normalise(files)
    checks = run_checks(series, cfg.tolerance)
    exts: list[External] = []
    if "binance_futures" in files:
        cut = ext.holdout_cut()
        exts = normalise_external(files["binance_futures"], cfg.coins, cut)
        checks.update(check_external(exts))
    hashes = [f.sha256 for got in files.values() for f in got.files]
    snapshot = {
        "schema": SCHEMA,
        "snapshot_id": compute_snapshot_id(hashes),
        "id_rule": ID_RULE,
        "created": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "build": {
            "sources": list(cfg.sources),
            "coins": list(cfg.coins),
            "intervals": list(cfg.intervals),
            "offline": cfg.offline,
            "tolerance": cfg.tolerance,
            "code": git_state(),
        },
        "sources": {
            name: {
                "files": [
                    {"path": f.path.relative_to(cfg.data_dir).as_posix(), "sha256": f.sha256, "bytes": f.bytes}
                    for f in sorted(got.files, key=lambda f: f.path)
                ],
                "note": SOURCE_NOTES[name],
                "details": got.notes,
            }
            for name, got in files.items()
        },
        "series": [],
        "checks": checks,
    }
    if exts:
        snapshot["positioning"] = {
            "cut": cut.isoformat(),
            "cut_rule": "only values known strictly before the close of the last validate bar (config/splits.yaml)",
            "rules": ext.RULES,
            "stale_after": fu.describe(fu.STALE_AFTER),
            "metrics_lag": fu.describe(fu.METRICS_LAG),
        }
    staging = cfg.data_dir / STAGING
    write_staging(staging, series, snapshot, exts)
    published, what = publish(staging, cfg.data_dir / "catalog", cfg.data_dir / "snapshots")
    log.info("snapshot %s: %s", published["snapshot_id"], what)
    result = {**published, "publish": what}
    if cfg.report_dir is not None:
        result["report"] = str(write_report(published, cfg.report_dir))
        if "external" in published:
            result["positioning_report"] = str(write_positioning_report(published, cfg.report_dir, result["report"]))
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = parse_args(argv)
    result = build(cfg)
    print(f"snapshot {result['snapshot_id']} ({result['publish']}), created {result['created']}")
    for s in result["series"]:
        print(f"  {s['bar_type']:40s} {s['rows']:>7d} bars  {s['start']} .. {s['end']}  gaps {s['gaps']}")
    for e in result.get("external", []):
        name = f"{e['symbol']} {e['table']}"
        print(f"  {name:40s} {e['rows']:>7d} rows  {e['first_ts']} .. {e['last_ts']}")
    for key in ("report", "positioning_report"):
        if key in result:
            print(f"{key.replace('_', ' ')}: {result[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
