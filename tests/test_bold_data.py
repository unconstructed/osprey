"""lab/data/bold.py: the momentum-bold daily bars (listing, download, store, load). Synthetic files and a fake
server only (httpx.MockTransport); no network."""

from __future__ import annotations

import hashlib
import io
import json
import runpy
import sys
import warnings
import zipfile

import httpx
import numpy as np
import pandas as pd
import pytest

from lab.data import bold, sources
from lab.data.external import HoldoutWindowError
from lab.runner import momentum

CUT = pd.Timestamp("2024-07-01", tz="UTC")
NS = bold.S3_NS["s3"]
ROOT = bold.LIST_PREFIX
NO_SLEEP = sources.Retry(max_retries=2, sleep=lambda s: None)


# --------------------------------------------------------------------------- synthetic files and a fake server


def day_line(open_ts: pd.Timestamp, d: int, *, qv: str | None = None, bad: bool = False) -> str:
    ms = open_ts.value // 10**6
    o, h, lo, c, v = 100.0 + d, 102.0 + d, 99.0 + d, 101.0 + d, 10.0 + d
    if bad:
        h, lo = lo, h  # high below low
    qv = f"{(10.0 + d) * 100.5}" if qv is None else qv
    return f"{ms},{o},{h},{lo},{c},{v},{ms + 86_400_000 - 1},{qv},10,1,1,0"


def month_csv(sym_month: tuple[int, int], *, skip=(), bad=(), dup=(), off_grid=(), no_qv=(), extra=()) -> str:
    start = pd.Timestamp(year=sym_month[0], month=sym_month[1], day=1, tz="UTC")
    lines = []
    for d in range(start.days_in_month):
        t = start + pd.Timedelta(days=d)
        if d in skip:
            continue
        lines.append(day_line(t, d, qv="" if d in no_qv else None, bad=d in bad))
        if d in dup:
            lines.append(day_line(t, d, qv="777.0"))
        if d in off_grid:
            lines.append(day_line(t + pd.Timedelta(hours=1), 50 + d))
    lines += [day_line(t, 90) for t in extra]
    return "\n".join(lines) + "\n"


def zip_of(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name.replace(".zip", ".csv"), text)
    return buf.getvalue()


class Bucket:
    """The fake data.binance.vision bucket: S3 list pages (``page`` entries each) on LIST_HOST and the files."""

    def __init__(self, page: int = 2):
        self.page, self.listed, self.served, self.requests = page, [], {}, []

    def add(self, sym: str, ym: tuple[int, int], text: str | None = None, *, serve=True, interval="1d", check=None):
        name = f"{sym}-{interval}-{ym[0]:04d}-{ym[1]:02d}.zip"
        key = f"{ROOT}{sym}/{interval}/{name}"
        data = zip_of(name, text if text is not None else month_csv(ym))
        check = check or f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        self.listed += [key, key + ".CHECKSUM"]
        if serve:
            self.served[key], self.served[key + ".CHECKSUM"] = data, check.encode()

    def xml(self, prefix: str, marker: str) -> bytes:
        entries = set()
        for k in self.listed:
            if k.startswith(prefix):
                rest = k[len(prefix) :]
                entries.add(prefix + rest.split("/")[0] + "/" if "/" in rest else k)
        entries = sorted(e for e in entries if e > marker)
        page, more = entries[: self.page], len(entries) > self.page
        body = "".join(
            f"<CommonPrefixes><Prefix>{e}</Prefix></CommonPrefixes>" if e.endswith("/") else f"<Contents><Key>{e}</Key></Contents>"
            for e in page
        )
        nxt = f"<NextMarker>{page[-1]}</NextMarker>" if more else ""
        return (
            f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{NS}"><Name>data.binance.vision</Name>'
            f"<Prefix>{prefix}</Prefix><MaxKeys>{self.page}</MaxKeys><IsTruncated>{str(more).lower()}</IsTruncated>"
            f"{nxt}{body}</ListBucketResult>"
        ).encode()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.host == bold.LIST_HOST:
            q = dict(request.url.params)
            return httpx.Response(200, content=self.xml(q["prefix"], q.get("marker", "")))
        key = request.url.path.lstrip("/")
        if request.url.host == "data.binance.vision" and key in self.served:
            return httpx.Response(200, content=self.served[key])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return sources.make_client(httpx.MockTransport(self))


def standard_bucket() -> Bucket:
    b = Bucket()
    for ym in [(2024, 4), (2024, 6), (2024, 7), (2024, 8)]:
        b.add("AAAUSDT", ym)
    b.add("AAAUSDT", (2024, 5), month_csv((2024, 5), skip={9}, bad={19}, dup={4}, off_grid={2}, no_qv={24}))
    b.add("BBBUSDT", (2023, 11))
    b.add("BBBUSDT", (2023, 12))
    b.add("CCCUSDT", (2024, 3), month_csv((2024, 3), bad=set(range(31))))
    b.add("DDDUSDT", (2024, 1), serve=False)
    b.add("DDDUSDT", (2024, 2))
    b.add("NEWUSDT", (2024, 8))
    b.add("ONLYHUSDT", (2024, 1), interval="1h")
    b.add("XYZBTC", (2024, 1))
    b.add("bad_USDT", (2024, 1))
    return b


@pytest.fixture
def built(tmp_path):
    b = standard_bucket()
    raw, cat = tmp_path / "raw", tmp_path / "catalog_bold"
    with b.client() as c:
        listing = bold.download(c, raw, cut=CUT, workers=2, retry=NO_SLEEP)
    snap = bold.build(raw, cat, cut=CUT, git={"commit": "test"})
    return b, raw, cat, listing, snap


# --------------------------------------------------------------------------- the listing


@pytest.mark.parametrize(
    ("url", "params"),
    [
        ("https://data.binance.vision/data.binance.vision", {"prefix": ROOT, "delimiter": "/"}),
        ("https://s3.amazonaws.com/data.binance.vision", {"prefix": ROOT, "delimiter": "/"}),
        ("http://s3-ap-northeast-1.amazonaws.com/data.binance.vision", {"prefix": ROOT, "delimiter": "/"}),
        ("https://u:p@s3-ap-northeast-1.amazonaws.com/data.binance.vision", {"prefix": ROOT, "delimiter": "/"}),
        ("https://s3-ap-northeast-1.amazonaws.com:8443/data.binance.vision", {"prefix": ROOT, "delimiter": "/"}),
        ("https://s3-ap-northeast-1.amazonaws.com/other-bucket", {"prefix": ROOT, "delimiter": "/"}),
        ("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision/data/x.zip", {"prefix": ROOT, "delimiter": "/"}),
        ("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?acl", {"prefix": ROOT, "delimiter": "/"}),
        (bold.LIST_URL, {"prefix": "data/futures/um/", "delimiter": "/"}),
        (bold.LIST_URL, {"prefix": "data/spot/monthly/klines/../../futures/", "delimiter": "/"}),
        (bold.LIST_URL, {"prefix": ROOT}),
        (bold.LIST_URL, {"prefix": ROOT, "delimiter": ","}),
        (bold.LIST_URL, {"prefix": ROOT, "delimiter": "/", "list-type": "2"}),
    ],
)
def test_the_listing_check_refuses_other_hosts_buckets_prefixes_and_requests(url, params):
    with pytest.raises(sources.DisallowedHostError):
        bold.check_list_request(url, params)


def test_the_listing_check_allows_the_approved_request():
    ok = bold.check_list_request(bold.LIST_URL, {"prefix": ROOT + "BTCUSDT/1d/", "delimiter": "/", "marker": "x"})
    assert ok.host == "s3-ap-northeast-1.amazonaws.com" and ok.path == "/data.binance.vision"


def test_the_listing_follows_next_marker_and_keeps_usdt_symbols():
    b = standard_bucket()
    with b.client() as c:
        symbols, refused, pages = bold.list_usdt_symbols(c, retry=NO_SLEEP)
        months = bold.list_months(c, "AAAUSDT", retry=NO_SLEEP)
    assert symbols == ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "NEWUSDT", "ONLYHUSDT"]
    assert refused == ["bad_USDT"] and pages == 4  # 8 folders, 2 a page
    assert months == [(2024, m) for m in range(4, 9)]  # 10 keys: 5 pages
    markers = [dict(httpx.URL(u).params).get("marker", "") for u in b.requests if bold.LIST_HOST in u]
    assert markers[:4] == ["", f"{ROOT}BBBUSDT/", f"{ROOT}DDDUSDT/", f"{ROOT}ONLYHUSDT/"]
    assert all(dict(httpx.URL(u).params)["delimiter"] == "/" for u in b.requests)


def page(body: str, truncated: str = "false", marker: str = "") -> bytes:
    nxt = f"<NextMarker>{marker}</NextMarker>" if marker else ""
    return f'<ListBucketResult xmlns="{NS}"><IsTruncated>{truncated}</IsTruncated>{nxt}{body}</ListBucketResult>'.encode()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"not xml <", "not XML"),
        (b"<Error><Code>AccessDenied</Code></Error>", "not a ListBucketResult"),
        (page("<Contents><Key>data/futures/x.zip</Key></Contents>"), "outside it"),
        (page(f"<Contents><Key>{ROOT}A/1d/a.zip</Key></Contents>", "true"), "without NextMarker"),
    ],
)
def test_a_bad_listing_page_is_refused(content, message):
    with pytest.raises(sources.DownloadError, match=message):
        bold.parse_listing(content, ROOT)


def test_a_marker_that_does_not_advance_stops_the_listing():
    def handler(request):
        return httpx.Response(200, content=page(f"<Contents><Key>{ROOT}A</Key></Contents>", "true", f"{ROOT}A"))

    with sources.make_client(httpx.MockTransport(handler)) as c, pytest.raises(sources.DownloadError, match="advance"):
        bold.list_all(c, ROOT, retry=NO_SLEEP)


def test_list_requests_retry_and_refuse_bad_answers(monkeypatch):
    answers = [httpx.Response(503), httpx.Response(200, content=page(f"<Contents><Key>{ROOT}A</Key></Contents>"))]
    with sources.make_client(httpx.MockTransport(lambda r: answers.pop(0))) as c:
        assert bold.list_page(c, ROOT, retry=NO_SLEEP) == ([], [f"{ROOT}A"], None)

    def down(request):
        raise httpx.ConnectError("down")

    with sources.make_client(httpx.MockTransport(down)) as c, pytest.raises(sources.DownloadError, match="3 tries"):
        bold.list_page(c, ROOT, retry=NO_SLEEP)
    with sources.make_client(httpx.MockTransport(lambda r: httpx.Response(403))) as c:
        with pytest.raises(sources.DownloadError, match="HTTP 403"):
            bold.list_page(c, ROOT, retry=NO_SLEEP)
    monkeypatch.setattr(bold, "LIST_MAX_BYTES", 10)
    with sources.make_client(httpx.MockTransport(lambda r: httpx.Response(200, content=page("")))) as c:
        with pytest.raises(sources.DownloadError, match="bytes"):
            bold.list_page(c, ROOT, retry=NO_SLEEP)


# --------------------------------------------------------------------------- the download


def test_nothing_after_june_2024_is_requested(built):
    b, raw, _, listing, _ = built
    zips = [u for u in b.requests if "data.binance.vision/data/" in u]
    assert zips and all(u.split("-1d-")[1][:7] <= "2024-06" for u in zips)
    assert not [u for u in zips if "NEWUSDT" in u or "XYZBTC" in u or "bad_" in u or "1h" in u]
    for ym in [(2024, 7), (2024, 12), (2025, 1)]:
        with pytest.raises(HoldoutWindowError):
            bold.month_url("AAAUSDT", ym, CUT)
    with pytest.raises(ValueError, match="not a USDT"):
        bold.month_url("../BTCUSDT", (2024, 1), CUT)
    assert bold.month_url("AAAUSDT", (2024, 6), CUT).endswith("/AAAUSDT/1d/AAAUSDT-1d-2024-06.zip")
    assert listing == json.loads((raw / bold.LISTING_FILE).read_text())
    assert listing["months"] == {
        "AAAUSDT": ["2024-04", "2024-05", "2024-06"],
        "BBBUSDT": ["2023-11", "2023-12"],
        "CCCUSDT": ["2024-03"],
        "DDDUSDT": ["2024-01", "2024-02"],
    }
    assert listing["no_daily_files"] == ["ONLYHUSDT"] and listing["first_month_after_window"] == 1
    assert listing["refused_names"] == ["bad_USDT"] and listing["missing"] == ["DDDUSDT-2024-01"]
    assert listing["status"] == {"downloaded and verified": 7, "missing": 1}
    assert not list(raw.glob("*/1d/*2024-07*")) and not (raw / "NEWUSDT").exists()


def test_files_on_disk_are_verified_and_a_checksum_failure_stops_the_download(built, tmp_path):
    b, raw, *_ = built
    n = len(b.requests)
    with b.client() as c:
        again = bold.download(c, raw, cut=CUT, workers=1, retry=NO_SLEEP, progress=lambda m: None)
    assert again["status"] == {"verified on disk": 7, "missing": 1}
    assert not [u for u in b.requests[n:] if u.endswith(".zip")]  # only listings and the 404 checksum
    path = raw / "AAAUSDT/1d/AAAUSDT-1d-2024-04.zip"
    path.write_bytes(path.read_bytes() + b"x")
    with b.client() as c, pytest.raises(sources.ChecksumError):
        bold.download_month(c, raw, "AAAUSDT", (2024, 4), CUT)
    bad = Bucket()
    bad.add("ZZZUSDT", (2024, 1), check="0" * 64 + "  ZZZUSDT-1d-2024-01.zip\n")
    with bad.client() as c, pytest.raises(sources.ChecksumError):
        bold.download(c, tmp_path / "raw2", cut=CUT, workers=1, retry=NO_SLEEP)
    assert not list((tmp_path / "raw2").rglob("*.zip*"))


# --------------------------------------------------------------------------- store and load


def test_bars_are_indexed_by_close_time_and_dropped_rows_are_counted(built):
    _, _, cat, _, snap = built
    frames = bold.load_bold_daily(CUT, cat)
    assert sorted(frames) == ["AAAUSDT", "BBBUSDT", "DDDUSDT"]
    a = frames["AAAUSDT"]
    assert list(a.columns) == list(bold.FIELDS) and (a.dtypes == np.float64).all()
    assert a.index.name == "ts" and str(a.index.tz) == "UTC" and a.index.unit == "us"
    # the bar of 2024-04-01 (opens 00:00) closes at 00:00 of 2024-04-02; the June 30 bar at the cut
    assert a.index[0] == pd.Timestamp("2024-04-02", tz="UTC") and a.index[-1] == CUT
    assert a.loc["2024-04-02", "close"].item() == 101.0 and a.loc["2024-04-02", "quote_volume"].item() == 1005.0
    assert a.loc["2024-05-06", "quote_volume"].item() == 777.0  # the duplicate's last row wins, as in the loader
    missing = {pd.Timestamp(f"2024-05-{d}", tz="UTC") for d in (11, 21, 26)}  # skipped, bad and no quote volume
    assert missing.isdisjoint(a.index) and len(a) == 30 + 28 + 30
    s = snap["symbols"]["AAAUSDT"]
    assert {k: s[k] for k in (*bold.COUNTS, "missing_days", "gaps", "months", "rows")} == {
        "rows_read": 92, "dropped_bad": 1, "dropped_off_grid": 1, "dropped_duplicates": 1,
        "dropped_quote_volume": 1, "missing_days": 3, "gaps": 3, "months": 3, "rows": 88,
    }  # fmt: skip
    assert not s["ends_before_cut"] and snap["symbols"]["BBBUSDT"]["ends_before_cut"]
    assert snap["symbols"]["CCCUSDT"]["rows"] == 0 and len(snap["symbols"]["CCCUSDT"]["empty_files"]) == 1
    assert snap["symbols"]["DDDUSDT"]["start"] == "2024-02-02T00:00:00+00:00"
    frames["BTCUSDT"] = frames.pop("AAAUSDT")  # the engine's panel needs BTCUSDT; the frames are its input as built
    momentum.make_wide_panel(frames, snapshot_id=snap["snapshot_id"])


def test_snapshot_json_holds_the_files_rows_and_hashes(built):
    _, raw, cat, _, snap = built
    assert snap == json.loads((cat / bold.SNAPSHOT_FILE).read_text())
    on_disk = sorted(p for p in raw.rglob("*") if p.is_file() and p.name != bold.LISTING_FILE)
    files = snap["sources"]["binance_bold"]["files"]
    assert sorted(f["path"] for f in files) == sorted(str(p.relative_to(raw)) for p in on_disk)
    for f in files:
        assert f["sha256"] == hashlib.sha256((raw / f["path"]).read_bytes()).hexdigest()
    digests = "\n".join(sorted(f["sha256"] for f in files))
    assert snap["snapshot_id"] == hashlib.sha256(digests.encode()).hexdigest()[:16]
    h = hashlib.sha256()
    for p in sorted((cat / "bars").glob("*.parquet")):
        f = pd.read_parquet(p)
        h.update(p.stem.encode())
        h.update(f.index.as_unit("ns").asi8.astype("<i8").tobytes())
        h.update(f.loc[:, list(bold.FIELDS)].to_numpy(dtype="<f8").tobytes())
    assert snap["content_sha256"] == h.hexdigest()
    assert bold.bold_snapshot(cat) == {
        "snapshot_id": snap["snapshot_id"], "sha256": h.hexdigest(), "content_sha256": h.hexdigest(), "symbols": 3
    }
    b = snap["symbols"]["BBBUSDT"]
    assert (b["rows"], b["start"], b["end"]) == (61, "2023-11-02T00:00:00+00:00", "2024-01-01T00:00:00+00:00")
    assert snap["sources"]["binance_bold"]["listing_sha256"] == hashlib.sha256(
        (raw / bold.LISTING_FILE).read_bytes()
    ).hexdigest()
    assert snap["cut"] == CUT.isoformat() and snap["build"] == {"commit": "test"}
    with pytest.raises(FileExistsError):
        bold.build(raw, cat, cut=CUT)
    p = cat / "bars" / "BBBUSDT.parquet"
    f = pd.read_parquet(p)
    f.iloc[3, 3] += 0.5
    f.to_parquet(p)
    with pytest.raises(sources.ChecksumError):
        bold.bold_snapshot(cat)


def test_a_build_whose_bars_do_not_read_back_is_refused(built, monkeypatch, tmp_path):
    _, raw, *_ = built
    monkeypatch.setattr(bold, "_read_all", lambda d, cut: {})
    with pytest.raises(sources.ChecksumError, match="read back"):
        bold.build(raw, tmp_path / "other", cut=CUT)
    assert not (tmp_path / "other").exists()


def test_the_test_window_guard_on_requests_and_returned_bars(built, tmp_path):
    _, _, cat, _, _ = built
    with pytest.raises(HoldoutWindowError):
        bold.load_bold_daily("2024-07-01 00:00:01", tmp_path / "does-not-exist")  # refused before reading
    with pytest.raises(HoldoutWindowError):
        bold.load_bold_daily(pd.Timestamp("2024-07-02", tz="Asia/Tokyo"), tmp_path / "does-not-exist")
    upto = bold.load_bold_daily("2024-02-02", cat)  # naive: UTC; the end close is included
    assert sorted(upto) == ["BBBUSDT", "DDDUSDT"] and upto["DDDUSDT"].index.tolist() == [pd.Timestamp("2024-02-02", tz="UTC")]
    assert upto["BBBUSDT"].attrs == {"symbol": "BBBUSDT", "snapshot_id": built[4]["snapshot_id"], "dropped_bad": 0}
    p = cat / "bars" / "DDDUSDT.parquet"
    f = pd.read_parquet(p)
    late = f.iloc[[-1]].copy()
    late.index = pd.DatetimeIndex([pd.Timestamp("2024-07-02", tz="UTC")], name="ts").as_unit("us")
    pd.concat([f, late]).to_parquet(p)
    with pytest.raises(HoldoutWindowError):
        bold.load_bold_daily("2024-01-01", cat)
    with pytest.raises(HoldoutWindowError):
        bold.bold_snapshot(cat)
    path = tmp_path / "AAAUSDT-1d-2024-06.zip"
    path.write_bytes(zip_of(path.name, month_csv((2024, 6), extra=[pd.Timestamp("2024-07-01", tz="UTC")])))
    with pytest.raises(HoldoutWindowError):
        bold.build_symbol([path], CUT)


def test_bad_stored_rows_are_dropped_and_counted_at_load(built):
    _, _, cat, _, _ = built
    p = cat / "bars" / "BBBUSDT.parquet"
    f = pd.read_parquet(p)
    f.iloc[0, 0] = -1.0  # a negative open
    f.iloc[1, 5] = np.nan  # no quote volume
    f.index = f.index.where(np.arange(len(f)) != 2, f.index[2] + pd.Timedelta(hours=1))  # off the 00:00 grid
    f.to_parquet(p)
    g = bold.load_bold_daily(CUT, cat)["BBBUSDT"]
    assert g.attrs["dropped_bad"] == 3 and len(g) == 58


# --------------------------------------------------------------------------- report and command line


def test_compare_closes_by_hand():
    idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"], utc=True), name="ts")
    a = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx)
    b = pd.DataFrame({"close": [1.0, 2.0 * (1 + 1e-6)]}, index=idx[:2])
    c = bold.compare_closes(a, b)
    assert c == {"common": 2, "only_bold": 1, "only_ref": 0, "max_rel_diff": pytest.approx(1e-6 / (1 + 1e-6)),
                 "over_1e-9": 1}
    assert bold.compare_closes(a.iloc[:1], b.iloc[1:])["max_rel_diff"] is None


def test_main_downloads_builds_and_reports(monkeypatch, tmp_path):
    b = standard_bucket()
    for sym, ym in [("BTCUSDT", (2024, 5)), ("BTCUSDT", (2024, 6)), ("ETHUSDT", (2024, 6))]:
        b.add(sym, ym)
    make = sources.make_client
    monkeypatch.setattr(sources, "make_client", lambda: make(httpx.MockTransport(b)))

    def load_bars(instrument, interval, end, catalog_dir):  # the main catalog's bars: these, ETH one day short
        frame = bold.load_bold_daily(end, tmp_path / "c1")[instrument.split(".")[0]]
        return frame.iloc[:-1] if instrument.startswith("ETH") else frame

    monkeypatch.setattr("lab.data.catalog.load_bars", load_bars)
    rep = tmp_path / "rep"
    args = ["--raw-dir", str(tmp_path / "r"), "--report-dir", str(rep), "--compare-catalog", "x", "--workers", "2"]
    assert bold.main([*args, "--catalog-dir", str(tmp_path / "c1")]) == 0
    assert bold.main([*args, "--catalog-dir", str(tmp_path / "c2"), "--build-only"]) == 0
    snap = json.loads((tmp_path / "c2" / bold.SNAPSHOT_FILE).read_text())
    [report] = rep.glob("*.md")
    text = report.read_text()
    assert report.name.endswith(f"-bold-{snap['snapshot_id']}.md") and snap["snapshot_id"] in text
    assert "Symbols stored: 5; rows: 269." in text  # 88 + 61 + 29 + BTC 61 + ETH 30
    assert "Stopped before the cut (no bar for 2024-06-30): 2; of them 2" in text  # BBB and DDD
    assert "DDDUSDT-2024-01" in text and "Zips with no valid row: 1" in text
    assert "| BTCUSDT | 61 | 0 | 0 | 0.0 | 0 |" in text and "| ETHUSDT | 29 | 1 | 0 | 0.0 | 0 |" in text
    monkeypatch.setattr(sys, "argv", ["bold", "--help"])
    with warnings.catch_warnings(), pytest.raises(SystemExit) as exc:
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: the module is already imported
        runpy.run_module("lab.data.bold", run_name="__main__")
    assert exc.value.code == 0

