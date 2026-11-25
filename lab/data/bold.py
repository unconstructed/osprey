"""Daily spot bars of every Binance ``*USDT`` pair, for the momentum-bold study (scouting only).

Build (``uv run python -m lab.data.bold``):

1. **List.** Every spot symbol under ``data/spot/monthly/klines/`` of the ``data.binance.vision`` bucket, delisted
   ones included, through the bucket's S3 list endpoint on :data:`LIST_HOST` (owner approval,
   ``reports/director/2026-11-25-owner-answer-momentum-bold.md`` item 6). :func:`check_list_request` allows that
   host, that bucket, that prefix and a GET list request (``prefix``, ``delimiter=/``, ``marker``) only. Pages hold
   1,000 entries; ``NextMarker`` is followed. A ``*USDT`` symbol's months come from listing its ``1d/`` folder.
2. **Download.** Each listed ``1d`` monthly zip whose days all close by the test-window cut (2024-07-01 00:00 UTC,
   ``external.holdout_cut``: months through 2024-06), and its ``.CHECKSUM``, from data.binance.vision through
   ``sources.fetch`` (its allow-list, retries and rate limit). :func:`month_url` refuses any later month before a
   request. Every zip is checked against its ``.CHECKSUM``; a mismatch stops the build. Raw files go to
   ``data/raw/binance_bold/<SYMBOL>/1d/``; ``LISTING.json`` there records the listing (months after the window are
   never recorded).
3. **Store.** ``data/catalog_bold/bars/<SYMBOL>.parquet`` (float64 ``open, high, low, close, volume,
   quote_volume``, index ``ts``: the UTC bar close time, open + 1 day, so a day's bar closes at 00:00 of the next
   day, as ``lab/data/panel.py``) and ``SNAPSHOT.json``: every raw file's SHA-256, rows, dates and drop counts per
   symbol, the snapshot id (:data:`ID_RULE`) and the content hash of the stored bars. ``data/catalog/`` is not
   touched, and an existing ``catalog_bold`` is never overwritten.

Parsing is ``loaders.load_binance_klines`` in grid mode (``interval="1d"``); ``quote_volume`` (Binance's quote
asset volume, which the loader does not return) is read from the same rows. Missing days stay missing; bad rows,
off-grid rows, duplicate days and rows without a valid quote volume are dropped and counted.

Load: :func:`load_bold_daily` and :func:`bold_snapshot`. Both refuse the test window: an ``end`` after the cut
before anything is read, and any stored bar closing after it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from lab.data import loaders, sources
from lab.data.external import HoldoutWindowError, holdout_cut

LIST_HOST = "s3-ap-northeast-1.amazonaws.com"
LIST_BUCKET = "data.binance.vision"
LIST_URL = f"https://{LIST_HOST}/{LIST_BUCKET}"
LIST_PREFIX = "data/spot/monthly/klines/"
LIST_PARAMS = frozenset({"prefix", "delimiter", "marker"})
LIST_MAX_BYTES = 8 << 20
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
INTERVAL = "1d"
GRID = pd.Timedelta(days=1)  # INTERVAL for the loader's grid mode (pandas 3 deprecates the string "1d")
QUOTE = "USDT"
SYMBOL_RE = re.compile(r"[0-9A-Z]{1,30}USDT")
FIELDS = ("open", "high", "low", "close", "volume", "quote_volume")
SCHEMA = "osprey.bold_snapshot/1"
ID_RULE = "first 16 hex of sha256 over the sorted raw-file sha256 hex digests joined by '\\n' (LISTING.json excluded)"
SNAPSHOT_FILE = "SNAPSHOT.json"
LISTING_FILE = "LISTING.json"
WORKERS = 8
DAY_NS = 86_400 * 10**9


# --------------------------------------------------------------------------- the listing (S3, read-only)


def check_list_request(url: str | httpx.URL, params: Mapping[str, str]) -> httpx.URL:
    """``url`` parsed, or :class:`sources.DisallowedHostError` unless it is a GET list request on the approved host,
    bucket and prefix: https on :data:`LIST_HOST`, path ``/data.binance.vision`` with no query of its own, and only
    ``prefix`` (under :data:`LIST_PREFIX`), ``delimiter`` (exactly ``/``) and ``marker`` as parameters."""
    parsed = httpx.URL(str(url))
    if parsed.scheme != "https" or parsed.userinfo or parsed.host != LIST_HOST or parsed.port not in (None, 443):
        raise sources.DisallowedHostError(f"listing is allowed on https://{LIST_HOST} only: {parsed.host}")
    if parsed.path != f"/{LIST_BUCKET}" or parsed.query:
        raise sources.DisallowedHostError(f"listing is allowed on bucket {LIST_BUCKET} only: {parsed.path}")
    if set(params) - LIST_PARAMS or params.get("delimiter") != "/":
        raise sources.DisallowedHostError(f"a list request takes prefix, delimiter '/' and marker only: {dict(params)}")
    prefix = params.get("prefix", "")
    if not prefix.startswith(LIST_PREFIX) or ".." in prefix:
        raise sources.DisallowedHostError(f"listing is allowed under {LIST_PREFIX} only: {prefix!r}")
    return parsed


def parse_listing(content: bytes, prefix: str) -> tuple[list[str], list[str], str | None]:
    """(common prefixes, keys, next marker or None) of one ``ListBucketResult`` page. Every entry must lie under
    ``prefix``; a truncated page must carry ``NextMarker`` (S3 always sends it with a delimiter)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise sources.DownloadError(f"listing of {prefix}: not XML ({exc})") from exc
    if root.tag != f"{{{S3_NS['s3']}}}ListBucketResult":
        raise sources.DownloadError(f"listing of {prefix}: not a ListBucketResult ({root.tag})")
    prefixes = [e.text or "" for e in root.findall("s3:CommonPrefixes/s3:Prefix", S3_NS)]
    keys = [e.text or "" for e in root.findall("s3:Contents/s3:Key", S3_NS)]
    outside = [x for x in prefixes + keys if not x.startswith(prefix)]
    if outside:
        raise sources.DownloadError(f"listing of {prefix}: entries outside it: {outside[:3]}")
    if root.findtext("s3:IsTruncated", "false", S3_NS) != "true":
        return prefixes, keys, None
    marker = root.findtext("s3:NextMarker", "", S3_NS)
    if not marker:
        raise sources.DownloadError(f"listing of {prefix}: a truncated page without NextMarker")
    return prefixes, keys, marker


def list_page(
    client: httpx.Client,
    prefix: str,
    marker: str = "",
    *,
    retry: sources.Retry | None = None,
    limiter: sources.RateLimiter | None = None,
) -> tuple[list[str], list[str], str | None]:
    """One list request (``sources.fetch`` allows data hosts only, so this is its own loop with the same
    :class:`sources.Retry` and :class:`sources.RateLimiter`; GET only, no redirects)."""
    params = {"prefix": prefix, "delimiter": "/"} | ({"marker": marker} if marker else {})
    url = check_list_request(LIST_URL, params)
    retry = retry or sources.Retry()
    last = ""
    for attempt in range(retry.max_retries + 1):
        if limiter is not None:
            limiter.wait()
        retry_after = None
        try:
            r = client.get(url, params=params, follow_redirects=False)
        except httpx.TransportError as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if r.status_code not in sources.RETRY_STATUSES:
                if r.status_code != 200 or len(r.content) > LIST_MAX_BYTES:
                    raise sources.DownloadError(f"listing of {prefix}: HTTP {r.status_code}, {len(r.content)} bytes")
                return parse_listing(r.content, prefix)
            last, retry_after = f"HTTP {r.status_code}", r.headers.get("retry-after")
        if attempt < retry.max_retries:
            retry.wait(attempt, retry_after)
    raise sources.DownloadError(f"listing of {prefix}: giving up after {retry.max_retries + 1} tries ({last})")


def list_all(client: httpx.Client, prefix: str, **kw) -> tuple[list[str], list[str], int]:
    """Every common prefix and key under ``prefix``, following ``NextMarker``; and the number of pages."""
    prefixes: list[str] = []
    keys: list[str] = []
    marker, pages = "", 0
    while True:
        p, k, nxt = list_page(client, prefix, marker, **kw)
        prefixes, keys, pages = prefixes + p, keys + k, pages + 1
        if nxt is None:
            return prefixes, keys, pages
        if nxt <= marker:
            raise sources.DownloadError(f"listing of {prefix}: NextMarker {nxt!r} does not advance")
        marker = nxt


def list_usdt_symbols(client: httpx.Client, **kw) -> tuple[list[str], list[str], int]:
    """(sorted ``*USDT`` symbols, ``*USDT`` names refused by :data:`SYMBOL_RE`, pages read)."""
    prefixes, _, pages = list_all(client, LIST_PREFIX, **kw)
    names = sorted(p[len(LIST_PREFIX) :].rstrip("/") for p in prefixes)
    usdt = [n for n in names if n.endswith(QUOTE)]
    return [n for n in usdt if SYMBOL_RE.fullmatch(n)], [n for n in usdt if not SYMBOL_RE.fullmatch(n)], pages


def list_months(client: httpx.Client, symbol: str, **kw) -> list[tuple[int, int]]:
    """The months whose ``1d`` zip is listed in ``symbol``'s folder, sorted."""
    folder = f"{LIST_PREFIX}{symbol}/{INTERVAL}/"
    _, keys, _ = list_all(client, folder, **kw)
    name = re.compile(re.escape(f"{folder}{symbol}-{INTERVAL}-") + r"(\d{4})-(\d{2})\.zip")
    return sorted({(int(m[1]), int(m[2])) for k in keys if (m := name.fullmatch(k))})


# --------------------------------------------------------------------------- the zips (data.binance.vision)


def month_closes_by(ym: tuple[int, int], cut: pd.Timestamp) -> bool:
    """True when every daily bar of month ``ym`` closes at or before ``cut`` (its last bar closes at 00:00 of the
    next month's first day)."""
    year, month = (ym[0] + 1, 1) if ym[1] == 12 else (ym[0], ym[1] + 1)
    return pd.Timestamp(year=year, month=month, day=1, tz="UTC") <= cut


def month_url(symbol: str, ym: tuple[int, int], cut: pd.Timestamp) -> str:
    """The zip URL of ``symbol``'s month ``ym``; :class:`HoldoutWindowError` for a month with a day in the test
    window, and ``ValueError`` for a name :data:`SYMBOL_RE` refuses, before any request."""
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"not a USDT spot symbol: {symbol!r}")
    if not month_closes_by(ym, cut):
        raise HoldoutWindowError(f"{symbol} {ym[0]:04d}-{ym[1]:02d} has days after {cut.isoformat()}")
    name = f"{symbol}-{INTERVAL}-{ym[0]:04d}-{ym[1]:02d}.zip"
    return sources.BINANCE_URL.format(sym=symbol, iv=INTERVAL, name=name)


def download_month(
    client: httpx.Client, raw_dir: Path, symbol: str, ym: tuple[int, int], cut: pd.Timestamp, **kw
) -> tuple[str, Path | None]:
    """Make sure one monthly zip and its ``.CHECKSUM`` are on disk and agree. Returns (status, zip path or None
    when the source answers 404). A mismatch raises :class:`sources.ChecksumError` and writes nothing."""
    url = month_url(symbol, ym, cut)
    path = raw_dir / symbol / INTERVAL / url.rsplit("/", 1)[1]
    check = path.with_name(path.name + ".CHECKSUM")
    if path.is_file() and check.is_file():
        sources.verify_checksum(path.read_bytes(), check.read_text(), path.name)
        return "verified on disk", path
    try:
        check_text = sources.fetch(client, url + ".CHECKSUM", max_bytes=4096, **kw).content
        data = sources.fetch(client, url, max_bytes=64 << 20, **kw).content
    except sources.NotFoundError:
        return "missing", None
    sources.verify_checksum(data, check_text.decode("utf-8"), path.name)
    sources.write_atomic(check, check_text)
    sources.write_atomic(path, data)
    return "downloaded and verified", path


def download(
    client: httpx.Client,
    raw_dir: Path,
    *,
    cut: pd.Timestamp,
    workers: int = WORKERS,
    progress: Callable[[str], None] = lambda msg: None,
    **kw,
) -> dict:
    """List, download and verify (module docstring); writes and returns ``LISTING.json``'s record."""
    raw_dir = Path(raw_dir)
    symbols, refused, pages = list_usdt_symbols(client, **kw)
    progress(f"listed {len(symbols)} USDT symbols in {pages} pages")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        listed = dict(zip(symbols, pool.map(lambda s: list_months(client, s, **kw), symbols), strict=True))
    months = {s: [ym for ym in m if month_closes_by(ym, cut)] for s, m in listed.items()}
    jobs = [(s, ym) for s in symbols for ym in months[s]]
    progress(f"{len(jobs)} monthly zips to fetch or verify")

    def run(job):
        return download_month(client, raw_dir, job[0], job[1], cut, **kw)

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (job, res) in enumerate(zip(jobs, pool.map(run, jobs), strict=True), start=1):
            results[job] = res
            if i % 500 == 0 or i == len(jobs):
                progress(f"{i}/{len(jobs)} zips done")
    status: dict[str, int] = {}
    for st, _ in results.values():
        status[st] = status.get(st, 0) + 1
    record = {
        "listed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "list_url": LIST_URL,
        "prefix": LIST_PREFIX,
        "pages": pages,
        "usdt_symbols": len(symbols),
        "refused_names": refused,
        "no_daily_files": [s for s in symbols if not listed[s]],
        "first_month_after_window": sum(1 for s in symbols if listed[s] and not months[s]),
        "cut": cut.isoformat(),
        "status": status,
        "missing": [f"{s}-{ym[0]:04d}-{ym[1]:02d}" for (s, ym), (_, p) in results.items() if p is None],
        "months": {s: [f"{y:04d}-{m:02d}" for y, m in months[s]] for s in symbols if months[s]},
    }
    sources.write_atomic(raw_dir / LISTING_FILE, (json.dumps(record, indent=1) + "\n").encode())
    return record


# --------------------------------------------------------------------------- parse and store


def read_month(path: Path) -> pd.DataFrame:
    """One monthly zip: ``loaders.load_binance_klines`` in grid mode (one day) plus the quote volume of the rows it
    kept (matched on close time and OHLCV, the last raw row winning, as the loader keeps the last duplicate). A row
    without a finite, non-negative quote volume is dropped and counted in ``attrs["dropped_quote_volume"]``."""
    bars = loaders.load_binance_klines(path, interval=GRID)
    raw, _, _ = loaders._read_fields(Path(path), 7, len(loaders.BINANCE_COLUMNS))
    keys = ["ts", *loaders.BAR_COLUMNS]
    rows = pd.DataFrame({name: pd.to_numeric(raw[i], errors="coerce").astype(float) for i, name in
                         enumerate(loaders.BAR_COLUMNS, start=1)})
    rows["quote_volume"] = pd.to_numeric(raw[7], errors="coerce").astype(float)
    opens = loaders.epoch_to_ns(raw[0])
    close_ns = (opens + DAY_NS).to_numpy(dtype="int64", na_value=0)  # a row without an open time matches nothing
    rows["ts"] = pd.to_datetime(close_ns, unit="ns", utc=True).as_unit("us")
    rows = rows.drop_duplicates(subset=keys, keep="last")
    merged = bars.reset_index().merge(rows, on=keys, how="left").set_index("ts")
    qv = merged["quote_volume"].to_numpy()
    ok = np.isfinite(qv) & (qv >= 0)
    out = merged.loc[ok, list(FIELDS)].astype(np.float64)
    out.attrs = {**bars.attrs, "dropped_quote_volume": int((~ok).sum())}
    return out


COUNTS = ("rows_read", "dropped_bad", "dropped_off_grid", "dropped_duplicates", "dropped_quote_volume")


def build_symbol(paths: list[Path], cut: pd.Timestamp) -> tuple[pd.DataFrame | None, dict]:
    """One symbol's bars from its monthly zips (sorted, duplicates across files dropped keeping the last), and its
    counts. A zip with no valid row adds its rows to ``dropped_bad`` and is listed in ``empty_files``."""
    counts = dict.fromkeys(COUNTS, 0) | {"empty_files": [], "short_bars": 0}
    frames = []
    for path in sorted(paths):
        try:
            f = read_month(path)
        except ValueError as exc:
            counts["empty_files"].append(f"{path.name}: {exc}")
            continue
        for key in COUNTS:
            counts[key] += f.attrs[key]
        counts["short_bars"] += len(f.attrs["short_bars"])
        frames.append(f)
    if not frames:
        return None, counts
    bars = pd.concat(frames).sort_index(kind="stable")
    dup = bars.index.duplicated(keep="last")
    counts["dropped_duplicates"] += int(dup.sum())
    bars = bars.loc[~dup]
    bars.index.name = "ts"
    if bars.index[-1] > cut:
        raise HoldoutWindowError(f"{paths[0].name}: a bar closes at {bars.index[-1].isoformat()}, after the cut")
    return bars, counts


def content_hash(frames: Mapping[str, pd.DataFrame]) -> str:
    """SHA-256 over every symbol (sorted): its name, close times as ns ``<i8`` and :data:`FIELDS` as ``<f8``."""
    digest = hashlib.sha256()
    for sym in sorted(frames):
        f = frames[sym]
        digest.update(sym.encode())
        digest.update(np.asarray(f.index.as_unit("ns").asi8, dtype="<i8").tobytes())
        digest.update(np.ascontiguousarray(f.loc[:, list(FIELDS)].to_numpy(dtype="<f8")).tobytes())
    return digest.hexdigest()


def snapshot_id_of(digests: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(digests)).encode()).hexdigest()[:16]


def _iso(ts: pd.Timestamp) -> str:
    return ts.isoformat()


def build(raw_dir: Path, catalog_dir: Path, *, cut: pd.Timestamp, git: dict | None = None) -> dict:
    """Parse every zip ``LISTING.json`` names, write ``catalog_dir`` (through a staging folder, never over an
    existing one) and return its snapshot. The stored bars are read back and must hash as built."""
    raw_dir, catalog_dir = Path(raw_dir), Path(catalog_dir)
    if catalog_dir.exists():
        raise FileExistsError(f"{catalog_dir} exists; a snapshot is never overwritten (move it aside first)")
    listing_path = raw_dir / LISTING_FILE
    listing = json.loads(listing_path.read_text())
    staging = catalog_dir.with_name(catalog_dir.name + ".staging")
    (staging / "bars").mkdir(parents=True, exist_ok=False)
    files, symbols, frames = [], {}, {}
    for sym, months in sorted(listing["months"].items()):
        paths = [raw_dir / sym / INTERVAL / f"{sym}-{INTERVAL}-{m}.zip" for m in months]
        paths = [p for p in paths if p.is_file()]
        for p in paths:
            check = p.with_name(p.name + ".CHECKSUM")
            sources.verify_checksum(p.read_bytes(), check.read_text(), p.name)
            files += [
                {"path": str(q.relative_to(raw_dir)), "sha256": sources.sha256_file(q), "bytes": q.stat().st_size}
                for q in (p, check)
            ]
        bars, counts = build_symbol(paths, cut)
        if bars is None:
            symbols[sym] = {"rows": 0, **counts}
            continue
        bars.to_parquet(staging / "bars" / f"{sym}.parquet")
        frames[sym] = bars
        days = (bars.index[-1] - bars.index[0]).days + 1
        symbols[sym] = {
            "rows": len(bars),
            "start": _iso(bars.index[0]),
            "end": _iso(bars.index[-1]),
            "months": len(paths),
            "missing_days": days - len(bars),
            "gaps": int((np.diff(bars.index.asi8) > 86_400 * 10**6).sum()),
            "ends_before_cut": bool(bars.index[-1] < cut),
            **counts,
        }
    content = content_hash(frames)
    snap = {
        "schema": SCHEMA,
        "snapshot_id": snapshot_id_of([f["sha256"] for f in files]),
        "id_rule": ID_RULE,
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build": git or {},
        "cut": cut.isoformat(),
        "interval": INTERVAL,
        "index": "ts: UTC bar close time = open + 1 day (00:00 of the next day), microseconds",
        "fields": list(FIELDS),
        "sources": {
            "binance_bold": {
                "zips_from": "https://data.binance.vision/" + LIST_PREFIX,
                "listing": {k: v for k, v in listing.items() if k != "months"},
                "listing_sha256": sources.sha256_file(listing_path),
                "verified": "every zip's SHA-256 matched its published .CHECKSUM file",
                "files": files,
            }
        },
        "symbols": symbols,
        "content_sha256": content,
    }
    (staging / SNAPSHOT_FILE).write_text(json.dumps(snap, indent=1) + "\n")
    if content_hash(_read_all(staging, cut)) != content:
        raise sources.ChecksumError(f"{staging}: the stored bars do not read back as built")
    staging.rename(catalog_dir)
    return snap


# --------------------------------------------------------------------------- load


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")


def _read_snapshot(catalog_dir: Path) -> dict:
    return json.loads((Path(catalog_dir) / SNAPSHOT_FILE).read_text())


def _read_symbol(catalog_dir: Path, sym: str, cut: pd.Timestamp, snapshot_id: str) -> pd.DataFrame:
    """One stored symbol, refused if any bar closes after ``cut``; invalid rows (not finite, prices <= 0, negative
    volume, high/low not around open and close, off the 00:00 grid, a repeated close) are dropped and counted."""
    f = pd.read_parquet(Path(catalog_dir) / "bars" / f"{sym}.parquet")
    idx = pd.DatetimeIndex(f.index).tz_convert("UTC").as_unit("us")
    if len(idx) and idx.max() > cut:
        raise HoldoutWindowError(f"{sym}: stored bars reach {idx.max().isoformat()}, after {cut.isoformat()}")
    f = f.loc[:, list(FIELDS)].astype(np.float64)
    f.index = pd.DatetimeIndex(idx, name="ts")
    f = f.sort_index(kind="stable")
    o, h, lo, c, v, qv = (f[k].to_numpy() for k in FIELDS)
    with np.errstate(invalid="ignore"):
        good = (
            np.isfinite(f.to_numpy()).all(axis=1)
            & (np.minimum(o, c) >= lo) & (np.maximum(o, c) <= h) & (lo > 0) & (v >= 0) & (qv >= 0)
            & (f.index == f.index.normalize()) & ~f.index.duplicated(keep="last")
        )
    f = f.loc[good]
    f.attrs = {"symbol": sym, "snapshot_id": snapshot_id, "dropped_bad": int((~good).sum())}
    return f


def _read_all(catalog_dir: Path, cut: pd.Timestamp) -> dict[str, pd.DataFrame]:
    snap = _read_snapshot(catalog_dir)
    syms = sorted(s for s, d in snap["symbols"].items() if d["rows"])
    return {s: _read_symbol(catalog_dir, s, cut, snap["snapshot_id"]) for s in syms}


def load_bold_daily(
    end, catalog_dir: str | Path = "data/catalog_bold", config_dir: Path | None = None
) -> dict[str, pd.DataFrame]:
    """Every stored symbol's daily bars with close time <= ``end`` (naive means UTC): ``{"BTCUSDT": frame}``, float64
    :data:`FIELDS`, index ``ts`` (tz-aware UTC close times, microseconds). Symbols with no bar by ``end`` are left
    out. Raises :class:`HoldoutWindowError` for an ``end`` after the cut before reading anything, and for stored bars
    after it. ``attrs``: ``symbol``, ``snapshot_id`` and ``dropped_bad`` (rows refused at load)."""
    end, cut = _utc(end), holdout_cut(config_dir)
    if end > cut:
        raise HoldoutWindowError(f"end {end.isoformat()} is after {cut.isoformat()} (the test window)")
    out = {}
    for sym, f in _read_all(Path(catalog_dir), cut).items():
        g = f.loc[:end]
        g.attrs = dict(f.attrs)
        if len(g):
            out[sym] = g
    return out


def bold_snapshot(catalog_dir: str | Path = "data/catalog_bold", config_dir: Path | None = None) -> dict:
    """``{"snapshot_id", "sha256", "content_sha256", "symbols"}`` of the stored snapshot, after recomputing the
    content hash from the stored bars (:class:`sources.ChecksumError` if they changed since the build)."""
    snap = _read_snapshot(Path(catalog_dir))
    got = content_hash(_read_all(Path(catalog_dir), holdout_cut(config_dir)))
    if got != snap["content_sha256"]:
        raise sources.ChecksumError(f"{catalog_dir}: stored bars hash {got}, SNAPSHOT.json says {snap['content_sha256']}")
    stored = sum(1 for d in snap["symbols"].values() if d["rows"])
    return {"snapshot_id": snap["snapshot_id"], "sha256": got, "content_sha256": got, "symbols": stored}


# --------------------------------------------------------------------------- report


def compare_closes(bold: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """Daily closes of the same symbol from this snapshot and another catalog, on their common closes."""
    common = bold.index.intersection(ref.index)
    a, b = bold.loc[common, "close"].to_numpy(), ref.loc[common, "close"].to_numpy()
    rel = np.abs(a - b) / np.abs(b) if len(common) else np.zeros(0)
    return {
        "common": len(common),
        "only_bold": len(bold.index.difference(ref.index)),
        "only_ref": len(ref.index.difference(bold.index)),
        "max_rel_diff": float(rel.max()) if len(rel) else None,
        "over_1e-9": int((rel > 1e-9).sum()),
    }


def render_report(snap: dict, comparison: Mapping[str, dict], command: str) -> str:
    """The quality report (markdown) from the snapshot and the cross-check."""
    syms = snap["symbols"]
    stored = {s: d for s, d in syms.items() if d["rows"]}
    cut = pd.Timestamp(snap["cut"])
    src = snap["sources"]["binance_bold"]
    lst = src["listing"]
    tot = {k: sum(d[k] for d in syms.values()) for k in (*COUNTS, "short_bars")}
    empty = [e for d in syms.values() for e in d["empty_files"]]
    ended = sorted(s for s, d in stored.items() if d["ends_before_cut"])
    before_june = [s for s in ended if pd.Timestamp(stored[s]["end"]) <= cut - pd.Timedelta(days=30)]
    gappy = sorted(stored, key=lambda s: (-stored[s]["missing_days"], s))
    gappy = [s for s in gappy if stored[s]["missing_days"]]
    lines = [
        f"# Data quality report: Binance USDT daily bars for momentum-bold, snapshot {snap['snapshot_id']}",
        "",
        f"Built {snap['created']}; content hash `{snap['content_sha256']}`; bars close at or before {snap['cut']}.",
        f"Command: `{command}`",
        "",
        "## Sources",
        "",
        f"- Listing: `{lst['list_url']}?prefix={lst['prefix']}&delimiter=/` ({lst['pages']} pages, listed "
        f"{lst['listed_at']}): {lst['usdt_symbols']} USDT symbols; {len(lst['no_daily_files'])} with no 1d file; "
        f"{lst['first_month_after_window']} whose first 1d month is after the window; "
        f"{len(lst['refused_names'])} names refused.",
        f"- Zips: {sum(1 for f in src['files'] if f['path'].endswith('.zip'))} from {src['zips_from']}, each checked "
        f"against its .CHECKSUM ({lst['status']}); listed months answering 404: {len(lst['missing'])} "
        f"{lst['missing'][:10]}.",
        "",
        "## Coverage",
        "",
        f"- Symbols stored: {len(stored)}; rows: {sum(d['rows'] for d in stored.values())}.",
        f"- First close: {min(d['start'] for d in stored.values())}; last close: "
        f"{max(d['end'] for d in stored.values())}.",
        f"- Stopped before the cut (no bar for 2024-06-30): {len(ended)}; of them {len(before_june)} with the last "
        f"close before 2024-06-01 (delisted before 2024-06).",
        "",
        "## Gaps and bad rows",
        "",
        f"- Missing days inside a symbol's own range (left missing, never filled): "
        f"{sum(d['missing_days'] for d in stored.values())} in {len(gappy)} symbols; most: "
        + ", ".join(f"{s} {stored[s]['missing_days']} ({stored[s]['gaps']} gaps)" for s in gappy[:10]) + ".",
        f"- Rows read {tot['rows_read']}; dropped as bad {tot['dropped_bad']}, off the 00:00 grid "
        f"{tot['dropped_off_grid']}, duplicate days {tot['dropped_duplicates']}, no valid quote volume "
        f"{tot['dropped_quote_volume']}; kept though shorter than a day (maintenance) {tot['short_bars']}.",
        f"- Zips with no valid row: {len(empty)} {empty[:5]}.",
        "",
        "## Cross-check with data/catalog (the same Binance source)",
        "",
        "| Symbol | Common closes | Only here | Only there | Max relative difference | Over 1e-9 |",
        "|---|---|---|---|---|---|",
    ]
    for sym, c in sorted(comparison.items()):
        lines.append(f"| {sym} | {c['common']} | {c['only_bold']} | {c['only_ref']} | {c['max_rel_diff']} | "
                     f"{c['over_1e-9']} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- command line


def reference_bars(catalog_dir: Path, cut: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """BTCUSDT and ETHUSDT daily bars of the main catalog, through the cut (lazy import: Nautilus)."""
    from lab.data import catalog

    return {s: catalog.load_bars(f"{s}.BINANCE", INTERVAL, end=cut, catalog_dir=catalog_dir)
            for s in ("BTCUSDT", "ETHUSDT")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raw-dir", default="data/raw/binance_bold")
    p.add_argument("--catalog-dir", default="data/catalog_bold")
    p.add_argument("--report-dir", default="reports/data")
    p.add_argument("--compare-catalog", default="data/catalog")
    p.add_argument("--workers", type=int, default=WORKERS)
    p.add_argument("--build-only", action="store_true", help="use LISTING.json and the zips on disk; no network")
    args = p.parse_args(argv)
    cut = holdout_cut()

    def say(msg: str) -> None:
        print(f"{datetime.now(UTC):%H:%M:%S} {msg}", file=sys.stderr, flush=True)

    if not args.build_only:
        with sources.make_client() as client:
            download(client, Path(args.raw_dir), cut=cut, workers=args.workers, progress=say,
                     limiter=sources.RateLimiter(0.02))
    from lab.data.build import git_state

    snap = build(Path(args.raw_dir), Path(args.catalog_dir), cut=cut, git=git_state())
    say(f"snapshot {snap['snapshot_id']} content {snap['content_sha256']}")
    frames = load_bold_daily(cut, args.catalog_dir)
    ref = reference_bars(Path(args.compare_catalog), cut)
    comparison = {s: compare_closes(frames[s], ref[s]) for s in ref}
    command = "uv run python -m lab.data.bold " + " ".join(argv if argv is not None else sys.argv[1:])
    out = Path(args.report_dir) / f"{datetime.now(UTC):%Y-%m-%d}-bold-{snap['snapshot_id']}.md"
    sources.write_atomic(out, render_report(snap, comparison, command.strip()).encode())
    say(f"report {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
