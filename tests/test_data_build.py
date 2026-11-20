"""lab/data/sources.py, lab/data/build.py, lab/data/report.py and the loader additions (Binance grid mode,
Coinbase candles). No network: every request goes to a fake server behind httpx.MockTransport. The Kraken
archive is a real zip built here and split into parts, served with HTTP range support like the real one.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import runpy
import threading
import time
import warnings
import zipfile
import zlib
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from lab.data import build as b
from lab.data import catalog as cat
from lab.data import report as rep
from lab.data import sources as src
from lab.data.loaders import load_binance_klines, load_coinbase_candles

H = pd.Timedelta(hours=1)
NOW = datetime(2017, 11, 15, 12, tzinfo=UTC)
START = pd.Timestamp("2017-08-01", tz="UTC")
DAYS = 92  # August to October 2017
BINANCE_DIR = "https://data.binance.vision/data/spot/monthly/klines/"
COINBASE = "https://api.exchange.coinbase.com/products/{}/candles"
OUTLIER_DAY = pd.Timestamp("2017-09-15", tz="UTC")
MAKE_CLIENT = src.make_client  # kept before any test patches it


# ============================================================================ a fake server


def serve_bytes(request: httpx.Request, body: bytes, etag: str | None) -> httpx.Response:
    headers = {"etag": etag} if etag else {}
    rng = request.headers.get("range")
    if rng:
        a, z = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", rng).groups())
        z = min(z, len(body) - 1)
        headers["content-range"] = f"bytes {a}-{z}/{len(body)}"
        return httpx.Response(206, content=body[a : z + 1], headers=headers)
    if request.method == "HEAD":
        return httpx.Response(200, headers={**headers, "content-length": str(len(body))})
    return httpx.Response(200, content=body, headers=headers)


class Server:
    """URL -> bytes (or a handler). Logs every request; ``script[url]`` answers first with the listed
    responses or raises the listed exceptions."""

    def __init__(self, routes: dict | None = None, etags: dict | None = None, delay: float = 0.0):
        self.routes = dict(routes or {})
        self.etags = dict(etags or {})
        self.script: dict[str, list] = {}
        self.log: list[tuple[str, str, dict]] = []
        self.delay = delay
        self._lock = threading.Lock()
        self.active = self.max_active = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        with self._lock:
            self.log.append((request.method, str(request.url), dict(request.headers)))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.script.get(url):
                item = self.script[url].pop(0)
                if isinstance(item, BaseException):
                    raise item
                return item
            route = self.routes.get(url)
            if route is None:
                return httpx.Response(404)
            if callable(route):
                return route(request)
            return serve_bytes(request, route, self.etags.get(url, '"etag-1"'))
        finally:
            with self._lock:
                self.active -= 1

    def client(self) -> httpx.Client:
        return MAKE_CLIENT(httpx.MockTransport(self))

    def gets(self, contains: str = "") -> list[str]:
        return [u for m, u, _ in self.log if m == "GET" and contains in u]


class Sleeps(list):
    def __call__(self, seconds):
        self.append(seconds)


def no_sleep_retry(max_retries=5, max_wait=60.0) -> tuple[src.Retry, Sleeps]:
    sleeps = Sleeps()
    return src.Retry(max_retries=max_retries, backoff=1.0, max_wait=max_wait, sleep=sleeps), sleeps


# ============================================================================ a small synthetic world


def truth(seed: int, base: float) -> pd.DataFrame:
    """Hourly bars indexed by OPEN time, prices with 2 decimals."""
    n = DAYS * 24
    rng = np.random.default_rng(seed)
    close = np.round(base * np.exp(np.cumsum(rng.normal(0, 0.004, n))), 2)
    open_ = np.concatenate([[round(base, 2)], close[:-1]])
    high = np.maximum(np.round(np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n)), 2), np.maximum(open_, close))
    low = np.minimum(np.round(np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n)), 2), np.minimum(open_, close))
    volume = np.round(rng.uniform(0.1, 10, n), 8)
    index = pd.DatetimeIndex(START + np.arange(n) * H)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index)


def daily_of(hourly: pd.DataFrame) -> pd.DataFrame:
    g = hourly.groupby(hourly.index.floor("D"))
    return pd.DataFrame(
        {"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
         "volume": g["volume"].sum()}
    )


def kraken_csv(bars: pd.DataFrame) -> bytes:
    rows = [
        f"{int(t.timestamp())},{float(r.open)!r},{float(r.high)!r},{float(r.low)!r},{float(r.close)!r},"
        f"{float(r.volume)!r},{i % 50 + 1}"
        for i, (t, r) in enumerate(bars.iterrows())
    ]
    return ("\n".join(rows) + "\n").encode()


def binance_rows(bars: pd.DataFrame, step_ms: int) -> list[list]:
    out = []
    for t, r in bars.iterrows():
        o = int(t.timestamp()) * 1000
        out.append([o, r.open, r.high, r.low, r.close, r.volume, o + step_ms - 1, 1.0, 10, 0.5, 0.5, 0])
    return out


def binance_zip(name: str, rows: list[list]) -> bytes:
    text = "\n".join(",".join(f"{x:.8f}" if isinstance(x, float) else str(x) for x in row) for row in rows) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name.replace(".zip", ".csv"), text)
    return buf.getvalue()


def make_kraken_archive(members: dict[str, bytes], parts: int = 3) -> tuple[bytes, list[bytes]]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", b"# test archive\n" * 200)
        zf.writestr("AIXBTUSD_1440.csv", b"1500000000,9.99,9.99,9.99,9.99,1.0,1\n")  # suffix decoys
        zf.writestr("CMETHUSD_60.csv", b"1500000000,1.5,1.5,1.5,1.5,1.0,1\n")
        for name, data in members.items():
            if name == "XBTUSD_60.csv":
                with zf.open(name, "w", force_zip64=True) as fh:  # the real archive is Zip64
                    fh.write(data)
            else:
                zf.writestr(name, data)
        zf.writestr("ZZPAD_1.csv", np.random.default_rng(0).integers(0, 255, 30000, dtype=np.uint8).tobytes())
    whole = buf.getvalue()
    cuts = [0, len(whole) // 3, 2 * len(whole) // 3 + 17, len(whole)][: parts + 1]
    cuts[-1] = len(whole)
    return whole, [whole[a:z] for a, z in zip(cuts[:-1], cuts[1:], strict=True)]


class World:
    """Kraken, Binance and Coinbase answers for BTC and ETH, August to October 2017."""

    def __init__(self):
        self.hourly = {"BTC": truth(1, 4000.0), "ETH": truth(2, 250.0)}
        self.daily = {c: daily_of(h) for c, h in self.hourly.items()}
        self.routes: dict = {}
        # Kraken: hourly with a few hours without trades (absent), daily consistent with it
        kraken_h = {"BTC": self.hourly["BTC"].drop(self.hourly["BTC"].index[500:503]),
                    "ETH": self.hourly["ETH"].drop(self.hourly["ETH"].index[[1000]])}
        self.kraken_hourly = kraken_h
        members = {
            "XBTUSD_1440.csv": kraken_csv(daily_of(kraken_h["BTC"])),
            "XBTUSD_60.csv": kraken_csv(kraken_h["BTC"]),
            "ETHUSD_1440.csv": kraken_csv(daily_of(kraken_h["ETH"])),
            "ETHUSD_60.csv": kraken_csv(kraken_h["ETH"]),
            "MANIFEST.json": json.dumps({"coverage": {"start": "2017-08-01", "end": "2017-10-31"},
                                         "generated": "2017-11-01", "release": "test"}).encode(),
        }
        self.members = members
        self.archive, parts = make_kraken_archive(members)
        sums = ""
        for i, part in enumerate(parts):
            name = f"Kraken_OHLCVT_Full.zip.part{i:02d}"
            self.routes[src.KRAKEN_BASE + name] = part
            sums += f"{hashlib.sha256(part).hexdigest()}  {name}\n"
        self.routes[src.KRAKEN_BASE + src.KRAKEN_SUMS] = sums.encode()
        # Binance: monthly zips; one outlier day in BTC daily; maintenance quirks in BTC hourly 2017-09
        for coin, sym in src.BINANCE_SYMBOLS.items():
            for iv, step_ms in (("1h", 3_600_000), ("1d", 86_400_000)):
                bars = self.hourly[coin] if iv == "1h" else self.daily[coin].copy()
                if coin == "BTC" and iv == "1d":
                    for col in ("open", "high", "low", "close"):
                        bars.loc[OUTLIER_DAY, col] = round(bars.loc[OUTLIER_DAY, col] * 1.03, 2)
                for month in (8, 9, 10):
                    name = f"{sym}-{iv}-2017-{month:02d}.zip"
                    rows = binance_rows(bars[bars.index.month == month], step_ms)
                    if coin == "BTC" and iv == "1h" and month == 9:
                        rows[10][6] = rows[10][0] + 1_200_000 - 1  # cut short by maintenance: kept
                        rows[20][5] = 0.0  # zero volume: dropped
                        rows[30][6] = rows[30][0] - 1000  # closes before it opens: bad
                        shifted = list(rows[40])
                        shifted[0] += 28 * 60_000
                        shifted[6] += 28 * 60_000
                        rows.insert(41, shifted)  # opens off the hour grid: dropped
                    data = binance_zip(name, rows)
                    url = f"{BINANCE_DIR}{sym}/{iv}/{name}"
                    self.routes[url] = data
                    self.routes[url + ".CHECKSUM"] = f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()
        for coin, product in src.COINBASE_PRODUCTS.items():
            self.routes[COINBASE.format(product)] = self.coinbase_handler(coin)

    def coinbase_handler(self, coin: str):
        daily = self.daily[coin]

        def handler(request: httpx.Request) -> httpx.Response:
            q = request.url.params
            assert q["granularity"] == "86400"
            lo, hi = pd.Timestamp(q["start"]), pd.Timestamp(q["end"])
            sel = daily[(daily.index >= lo) & (daily.index <= hi)].iloc[::-1]  # newest first
            rows = [[int(t.timestamp()), r.low, r.high, r.open, r.close, r.volume] for t, r in sel.iterrows()]
            return httpx.Response(200, json=rows)

        return handler

    def server(self, **kw) -> Server:
        return Server(self.routes, **kw)


@pytest.fixture(scope="module")
def world() -> World:
    return World()


# ============================================================================ the single request path


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/data.zip",
        "http://data.binance.vision/data/x.zip",
        "https://user:pw@data.binance.vision/x",
        "https://data.binance.vision:8443/x",
        "https://data.binance.vision.example.com/x",
        "https://example.com/?h=data.binance.vision",
        "ftp://assets.kraken.com/x",
    ],
)
def test_allow_list_refuses_before_any_request(url):
    server = Server({})
    with server.client() as c, pytest.raises(src.DisallowedHostError):
        src.fetch(c, url)
    assert server.log == []


def test_allowed_hosts_are_exactly_the_data_sources():
    assert src.ALLOWED_HOSTS == {
        "data.binance.vision", "assets.kraken.com", "api.kraken.com", "api.exchange.coinbase.com",
    }
    assert str(src.check_url("https://api.kraken.com:443/0/public/Time").host) == "api.kraken.com"


def test_only_get_and_head_and_the_generic_user_agent():
    url = "https://assets.kraken.com/x"
    server = Server({url: b"hello"})
    with server.client() as c:
        with pytest.raises(ValueError, match="only GET and HEAD"):
            src.fetch(c, url, method="POST")
        got = src.fetch(c, url)
    assert got.content == b"hello" and got.status == 200 and got.url == url
    assert server.log[0][2]["user-agent"] == "strategy-lab/0.1"


@pytest.mark.parametrize("target", ["https://evil.example.com/x", "https://assets.kraken.com/elsewhere"])
def test_redirects_are_never_followed(target):
    url = "https://assets.kraken.com/x"
    server = Server({url: lambda r: httpx.Response(302, headers={"location": target})})
    with server.client() as c, pytest.raises(src.DownloadError, match="HTTP 302"):
        src.fetch(c, url)
    assert len(server.log) == 1


def test_retries_429_and_5xx_with_backoff_and_retry_after():
    url = "https://data.binance.vision/x"
    server = Server({url: b"ok"})
    server.script[url] = [httpx.Response(503), httpx.Response(429, headers={"retry-after": "7"}),
                          httpx.Response(502, headers={"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}),
                          httpx.Response(429, headers={"retry-after": "999"})]
    retry, sleeps = no_sleep_retry(max_wait=30.0)
    with server.client() as c:
        assert src.fetch(c, url, retry=retry).content == b"ok"
    assert sleeps == [1.0, 7.0, 4.0, 30.0]  # backoff 2**0; Retry-After; a date falls back to 2**2; capped
    assert len(server.log) == 5


def test_transport_errors_are_retried_then_give_up():
    url = "https://data.binance.vision/x"
    server = Server({url: b"ok"})
    req = httpx.Request("GET", url)
    server.script[url] = [httpx.ConnectError("reset", request=req), httpx.ReadTimeout("slow", request=req)]
    retry, sleeps = no_sleep_retry()
    with server.client() as c:
        assert src.fetch(c, url, retry=retry).content == b"ok"
    assert sleeps == [1.0, 2.0]
    server.script[url] = [httpx.Response(500)] * 3
    retry, sleeps = no_sleep_retry(max_retries=2)
    with server.client() as c, pytest.raises(src.DownloadError, match="giving up after 3 tries .HTTP 500"):
        src.fetch(c, url, retry=retry)
    assert sleeps == [1.0, 2.0]


def test_status_handling():
    base = "https://assets.kraken.com/"
    server = Server({base + "teapot": lambda r: httpx.Response(418), base + "part": lambda r: httpx.Response(206)})
    with server.client() as c:
        with pytest.raises(src.NotFoundError, match="404"):
            src.fetch(c, base + "missing")
        with pytest.raises(src.DownloadError, match="HTTP 418"):
            src.fetch(c, base + "teapot")
        with pytest.raises(src.DownloadError, match=r"HTTP 206, expected \[200\]"):
            src.fetch(c, base + "part")
    assert issubclass(src.NotFoundError, src.DownloadError)


def test_body_size_limits():
    base = "https://assets.kraken.com/"
    server = Server({base + "big": b"x" * 100,
                     base + "stream": lambda r: httpx.Response(200, content=iter([b"y" * 60, b"y" * 60]))})
    with server.client() as c:
        with pytest.raises(src.DownloadError, match="100 bytes is over the 50 byte limit"):
            src.fetch(c, base + "big", max_bytes=50)
        with pytest.raises(src.DownloadError, match="body over the 100 byte limit"):
            src.fetch(c, base + "stream", max_bytes=100)
        head = src.fetch(c, base + "big", method="HEAD", max_bytes=50)  # a HEAD's length is the file's, not a body
    assert head.headers["content-length"] == "100" and head.content == b""


def test_rate_limiter_spaces_requests():
    clock = iter([0.0, 0.1, 10.0])
    sleeps = Sleeps()
    limiter = src.RateLimiter(0.34, clock=lambda: next(clock), sleep=sleeps)
    limiter.wait()
    limiter.wait()  # 0.1 s after the first: waits until 0.34
    limiter.wait()  # long after: no wait
    assert sleeps == [pytest.approx(0.24)]


def test_hash_helpers_and_atomic_write(tmp_path):
    path = tmp_path / "a" / "b.bin"
    src.write_atomic(path, b"abc")
    assert path.read_bytes() == b"abc" and not path.with_name("b.bin.tmp").exists()
    rf = src.RawFile.of(path)
    assert rf.sha256 == hashlib.sha256(b"abc").hexdigest() == src.sha256_bytes(b"abc") and rf.bytes == 3


def test_parse_sha256sums():
    h = "a" * 64
    assert src.parse_sha256sums(f"{h}  one.zip\n\n{h.upper()} *two.zip\n") == {"one.zip": h, "two.zip": h}
    with pytest.raises(src.ChecksumError, match="not a sha256sum line"):
        src.parse_sha256sums("deadbeef  x.zip")
    with pytest.raises(src.ChecksumError, match="lists no files"):
        src.parse_sha256sums("\n")


def test_kraken_part_names_must_be_consecutive():
    h = "0" * 64
    parts = {f"Kraken_OHLCVT_Full.zip.part{i:02d}": h for i in (1, 0, 2)}
    assert src.kraken_part_names({**parts, "other.txt": h}) == sorted(parts)
    with pytest.raises(src.DownloadError, match="unexpected archive parts"):
        src.kraken_part_names({"Kraken_OHLCVT_Full.zip.part00": h, "Kraken_OHLCVT_Full.zip.part02": h})
    with pytest.raises(src.DownloadError, match="unexpected archive parts"):
        src.kraken_part_names({"README": h})


def test_selection_is_checked(tmp_path):
    with pytest.raises(ValueError, match="coins must be from"):
        src.download_binance(None, tmp_path, ["DOGE"], ["1d"], now=NOW)
    with pytest.raises(ValueError, match="coins must be from"):
        src.download_kraken(None, tmp_path, ["BTC"], [], now=NOW)


# ============================================================================ multi-part range reader


def split_server(data: bytes, cuts: list[int], etag: str | None = '"v1"') -> tuple[Server, list[str]]:
    urls = [f"https://assets.kraken.com/f.part{i}" for i in range(len(cuts) - 1)]
    routes = {u: data[a:z] for u, a, z in zip(urls, cuts[:-1], cuts[1:], strict=True)}
    return Server(routes, etags={u: etag for u in urls}), urls


def test_reader_reads_the_concatenation_across_parts():
    data = bytes(np.random.default_rng(5).integers(0, 256, 1000, dtype=np.uint8))
    server, urls = split_server(data, [0, 300, 301, 1000])
    with server.client() as c:
        r = src.MultiPartHTTPReader(c, urls)
        assert r.total == 1000 and [p["bytes"] for p in r.parts] == [300, 1, 699] and r.readable() and r.seekable()
        for offset, size in [(0, 10), (295, 10), (299, 3), (990, 50), (0, 1000), (500, 0)]:
            r.seek(offset)
            assert r.read(size) == data[offset : offset + size] and r.tell() == min(offset + size, 1000)
        assert r.seek(-5, 2) == 995 and r.read() == data[995:]
        assert r.read(10) == b""  # at the end
        r.seek(100)
        assert r.seek(-40, 1) == 60
        with pytest.raises(ValueError, match="negative seek"):
            r.seek(-1)
    assert r.fetched == sum(n for n in (10, 10, 3, 10, 1000, 5)) and r.requests >= 6
    assert all(h.get("accept-encoding") == "identity" for m, _, h in server.log if m == "GET")


def test_reader_refuses_a_server_that_ignores_range():
    data = b"z" * 100
    server, urls = split_server(data, [0, 100])
    server.routes[urls[0]] = lambda r: httpx.Response(200, content=data) if r.method == "GET" else serve_bytes(r, data, None)
    with server.client() as c:
        r = src.MultiPartHTTPReader(c, urls)
        with pytest.raises(src.DownloadError, match="HTTP 200, expected"):
            r.read(10)


def test_reader_checks_content_range_length_and_etag():
    data = b"q" * 100
    server, urls = split_server(data, [0, 100])
    with server.client() as c:
        r = src.MultiPartHTTPReader(c, urls)
        server.script[urls[0]] = [httpx.Response(206, content=b"q" * 10, headers={"content-range": "bytes 1-10/100", "etag": '"v1"'})]
        with pytest.raises(src.DownloadError, match="asked for bytes 0-9/100, got bytes 1-10/100"):
            r.read(10)
        r.seek(0)
        server.script[urls[0]] = [httpx.Response(206, content=b"q" * 5, headers={"content-range": "bytes 0-9/100", "etag": '"v1"'})]
        with pytest.raises(src.DownloadError, match="with 5 bytes"):
            r.read(10)
        r.seek(0)
        server.etags[urls[0]] = '"v2"'
        with pytest.raises(src.DownloadError, match="ETag changed"):
            r.read(10)
        r.seek(0)
        server.etags[urls[0]] = None  # an answer without the ETag can't prove the part is unchanged
        with pytest.raises(src.DownloadError, match="ETag changed"):
            r.read(10)


def test_reader_without_etag_and_without_length():
    server, urls = split_server(b"abc" * 10, [0, 30], etag=None)
    with server.client() as c:
        r = src.MultiPartHTTPReader(c, urls)
        assert r.parts[0]["etag"] is None and r.read(5) == b"abcab"
        server.routes[urls[0]] = lambda req: httpx.Response(200)
        with pytest.raises(src.DownloadError, match="no usable Content-Length"):
            src.MultiPartHTTPReader(c, urls)


def test_extract_members_by_exact_name_from_a_split_real_zip(world):
    server, urls = split_server(world.archive, [0, 1000, 5000, len(world.archive)])
    names = ["XBTUSD_1440.csv", "XBTUSD_60.csv", "MANIFEST.json"]
    with server.client() as c:
        reader = src.MultiPartHTTPReader(c, urls)
        got, n = src.extract_members(reader, names)
    assert n == 9 and set(got) == set(names)
    for name in names:
        data, info = got[name]
        assert data == world.members[name] and info.CRC == zlib.crc32(data)
    assert all(h.get("range") for m, _, h in server.log if m == "GET")  # nothing but range reads


def test_extract_members_missing_and_duplicate_names():
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # zipfile warns about the duplicate on purpose
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("XBTUSD_1440.csv", b"a")
            zf.writestr("XBTUSD_1440.csv", b"b")
            zf.writestr("AIXBTUSD_60.csv", b"c")
    server, urls = split_server(buf.getvalue(), [0, len(buf.getvalue())])
    with server.client() as c:
        with pytest.raises(src.DownloadError, match="2 members named exactly 'XBTUSD_1440.csv'"):
            src.extract_members(src.MultiPartHTTPReader(c, urls), ["XBTUSD_1440.csv"])
        with pytest.raises(src.DownloadError, match="0 members named exactly 'XBTUSD_60.csv'"):
            src.extract_members(src.MultiPartHTTPReader(c, urls), ["XBTUSD_60.csv"])


def test_extract_members_detects_a_corrupt_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("XBTUSD_1440.csv", b"1500000000,1,1,1,1,1,1\n" * 20)
    data = bytearray(buf.getvalue())
    at = data.index(b"1500000000,1,1,1,1,1,1\n") + 5
    data[at] ^= 0x01  # one flipped bit in the member's bytes
    server, urls = split_server(bytes(data), [0, 100, len(data)])
    with server.client() as c, pytest.raises(zipfile.BadZipFile, match="CRC"):
        src.extract_members(src.MultiPartHTTPReader(c, urls), ["XBTUSD_1440.csv"])


# ============================================================================ kraken


KRAKEN_ALL = ["ETHUSD_1440.csv", "ETHUSD_60.csv", "MANIFEST.json", "XBTUSD_1440.csv", "XBTUSD_60.csv"]


def test_kraken_download_extracts_exact_members_and_records_provenance(world, tmp_path):
    server = world.server()
    with server.client() as c:
        out = src.download_kraken(c, tmp_path, ["BTC", "ETH"], ["1d", "1h"], now=NOW)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted([*KRAKEN_ALL, src.KRAKEN_SUMS, src.KRAKEN_PROVENANCE])  # no decoys
    for name in KRAKEN_ALL:
        assert (tmp_path / name).read_bytes() == world.members[name]
    assert {f.path.name for f in out.files} == {*KRAKEN_ALL, src.KRAKEN_SUMS}
    assert out.series[("BTC", "1h")] == [tmp_path / "XBTUSD_60.csv"]
    prov = json.loads((tmp_path / src.KRAKEN_PROVENANCE).read_text())
    assert prov["archive"]["members_in_archive"] == 9 and len(prov["archive"]["parts"]) == 3
    assert prov["members"]["XBTUSD_60.csv"]["sha256"] == hashlib.sha256(world.members["XBTUSD_60.csv"]).hexdigest()
    assert out.notes["manifest"]["release"] == "test" and "NOT the whole-archive SHA-256" in out.notes["verified"]
    assert out.notes["action"].startswith("online: members extracted")
    assert all(u.startswith("https://assets.kraken.com/") for _, u, _ in server.log)

    # same archive again: verified on disk, only the sums file and the HEADs are fetched
    again = world.server()
    with again.client() as c:
        out2 = src.download_kraken(c, tmp_path, ["BTC", "ETH"], ["1d", "1h"], now=NOW)
    assert out2.notes["action"].startswith("online: archive unchanged")
    assert again.gets() == [src.KRAKEN_BASE + src.KRAKEN_SUMS]
    assert [f.sha256 for f in out2.files] == [f.sha256 for f in out.files]

    # a new archive (other ETag): extracted again
    changed = world.server(etags={src.KRAKEN_BASE + "Kraken_OHLCVT_Full.zip.part01": '"v9"'})
    with changed.client() as c:
        out3 = src.download_kraken(c, tmp_path, ["BTC"], ["1d"], now=NOW)
    assert out3.notes["action"].startswith("online: members extracted") and len(changed.gets()) > 1


def test_kraken_offline_verifies_files_on_disk(world, tmp_path):
    with pytest.raises(FileNotFoundError, match="offline build"):
        src.download_kraken(None, tmp_path, ["BTC"], ["1d"], now=NOW)
    with world.server().client() as c:
        src.download_kraken(c, tmp_path, ["BTC"], ["1d"], now=NOW)
    out = src.download_kraken(None, tmp_path, ["BTC"], ["1d"], now=NOW)
    assert out.notes["action"].startswith("offline: verified")
    with pytest.raises(FileNotFoundError):  # ETH was never extracted
        src.download_kraken(None, tmp_path, ["ETH"], ["1d"], now=NOW)
    (tmp_path / src.KRAKEN_SUMS).unlink()
    with pytest.raises(FileNotFoundError):
        src.download_kraken(None, tmp_path, ["BTC"], ["1d"], now=NOW)


def test_kraken_changed_file_on_disk_is_refused(world, tmp_path):
    with world.server().client() as c:
        src.download_kraken(c, tmp_path, ["BTC"], ["1d"], now=NOW)
    path = tmp_path / "XBTUSD_1440.csv"
    path.write_bytes(path.read_bytes().replace(b",", b";", 1))
    with pytest.raises(src.ChecksumError, match="no longer matches"):
        src.download_kraken(None, tmp_path, ["BTC"], ["1d"], now=NOW)


# ============================================================================ binance


def test_months():
    assert src.month_range((2017, 11), (2018, 2)) == [(2017, 11), (2017, 12), (2018, 1), (2018, 2)]
    assert src.month_range((2018, 2), (2018, 1)) == []
    assert src.last_complete_month(datetime(2026, 11, 20, tzinfo=UTC)) == (2026, 10)
    assert src.last_complete_month(datetime(2027, 1, 1, 0, 30, tzinfo=UTC)) == (2026, 12)


def test_verify_checksum():
    data = b"zip bytes"
    good = f"{hashlib.sha256(data).hexdigest()}  a.zip\n"
    assert src.verify_checksum(data, good, "a.zip") == hashlib.sha256(data).hexdigest()
    with pytest.raises(src.ChecksumError, match="does not match"):
        src.verify_checksum(data + b"!", good, "a.zip")
    with pytest.raises(src.ChecksumError, match="checksum file is for"):
        src.verify_checksum(data, good, "b.zip")


def test_binance_download_verifies_every_zip_and_skips_verified_files(world, tmp_path):
    server = world.server(delay=0.003)
    with server.client() as c:
        out = src.download_binance(c, tmp_path, ["BTC", "ETH"], ["1d", "1h"], now=NOW)
    assert out.notes["zips"] == 12 and out.notes["missing"] == [] and out.notes["months"] == "2017-08 to 2017-10"
    assert out.notes["status"] == {"downloaded and verified": 12} and len(out.files) == 24
    assert 1 < server.max_active <= src.BINANCE_WORKERS
    assert [p.name for p in out.series[("BTC", "1h")]] == [f"BTCUSDT-1h-2017-{m:02d}.zip" for m in (8, 9, 10)]
    again = world.server()
    with again.client() as c:
        out2 = src.download_binance(c, tmp_path, ["BTC", "ETH"], ["1d", "1h"], now=NOW)
    assert again.log == [] and out2.notes["status"] == {"verified on disk": 12}
    offline = src.download_binance(None, tmp_path, ["BTC"], ["1d"], now=datetime(2017, 12, 2, tzinfo=UTC))
    assert offline.notes["missing"] == ["BTCUSDT-1d-2017-11"] and offline.notes["status"]["missing"] == 1


def test_binance_missing_month_and_bad_checksum(world, tmp_path):
    routes = dict(world.routes)
    del routes[f"{BINANCE_DIR}ETHUSDT/1d/ETHUSDT-1d-2017-09.zip.CHECKSUM"]
    bad_url = f"{BINANCE_DIR}BTCUSDT/1d/BTCUSDT-1d-2017-08.zip"
    with Server(routes).client() as c:
        out = src.download_binance(c, tmp_path, ["ETH"], ["1d"], now=NOW)
    assert out.notes["missing"] == ["ETHUSDT-1d-2017-09"] and len(out.series[("ETH", "1d")]) == 2
    routes[bad_url] = routes[bad_url] + b"tampered"
    with Server(routes).client() as c, pytest.raises(src.ChecksumError, match="does not match the published"):
        src.download_binance(c, tmp_path, ["BTC"], ["1d"], now=NOW)
    assert not (tmp_path / "BTCUSDT" / "1d" / "BTCUSDT-1d-2017-08.zip").exists()  # never written


def test_binance_changed_zip_on_disk_is_refused(world, tmp_path):
    with world.server().client() as c:
        src.download_binance(c, tmp_path, ["BTC"], ["1d"], now=NOW)
    path = tmp_path / "BTCUSDT" / "1d" / "BTCUSDT-1d-2017-09.zip"
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(src.ChecksumError):
        src.download_binance(None, tmp_path, ["BTC"], ["1d"], now=NOW)


# ============================================================================ coinbase


def test_coinbase_pages_and_last_complete_day():
    assert src.last_complete_day(datetime(2017, 11, 15, 12, tzinfo=UTC)) == date(2017, 11, 14)
    assert src.last_complete_day(datetime(2017, 11, 15, 0, 30, tzinfo=UTC)) == date(2017, 11, 13)  # settling
    pages = src.coinbase_pages(date(2016, 6, 1))
    assert pages == [(date(2015, 7, 20), date(2016, 5, 14)), (date(2016, 5, 15), date(2016, 6, 1))]
    assert all((z - a).days < 300 for a, z in pages) and src.coinbase_pages(date(2015, 7, 19)) == []


@pytest.mark.parametrize(
    "payload, match",
    [
        ({"message": "bad"}, "not a JSON list"),
        ([[1504224000, 1, 2, 1, 1]], "unexpected candle row"),
        ([[1504224000, 1, 2, 1, 1, True]], "unexpected candle row"),
        ([[1504224000, 1, 2, "1", 1, 1]], "unexpected candle row"),
        ([[1504224001, 1, 2, 1, 1, 1]], "unexpected candle row"),  # not a whole day
        ([[1504310400, 1, 2, 1, 1, 1]], "unexpected candle row"),  # 2017-09-02: outside the window
    ],
)
def test_check_candles(payload, match):
    with pytest.raises(ValueError, match=match):
        src.check_candles(json.dumps(payload).encode(), date(2017, 8, 31), date(2017, 9, 1))


def test_check_candles_accepts_the_window_edges():
    rows = [[1504224000, 1.5, 2, 1.5, 2, 3.25], [1504137600, 1, 2, 1, 1, 0]]
    assert src.check_candles(json.dumps(rows).encode(), date(2017, 8, 31), date(2017, 9, 1)) == rows


def test_coinbase_download_refetches_only_the_partial_page(world, tmp_path):
    server = world.server()
    sleeps = Sleeps()
    limiter = src.RateLimiter(0.34, clock=lambda: 0.0, sleep=sleeps)
    with server.client() as c:
        out = src.download_coinbase(c, tmp_path, ["BTC"], now=NOW, limiter=limiter)
    names = [p.name for p in out.series[("BTC", "1d")]]
    assert names == ["BTC-USD_86400_2015-07-20_2016-05-14.json", "BTC-USD_86400_2016-05-15_2017-03-10.json",
                     "BTC-USD_86400_2017-03-11_2017-11-14.json"]
    assert out.notes["pages"] == 3 and out.notes["fetched_now"] == 3 and len(sleeps) == 2
    q = httpx.URL(server.log[-1][1]).params
    assert (q["start"], q["end"], q["granularity"]) == ("2017-03-11T00:00:00Z", "2017-11-14T00:00:00Z", "86400")
    later = world.server()
    with later.client() as c:
        out2 = src.download_coinbase(c, tmp_path, ["BTC"], now=datetime(2017, 11, 20, 3, tzinfo=UTC), limiter=limiter)
    assert out2.notes["fetched_now"] == 1 and len(later.log) == 1
    assert [p.name for p in sorted((tmp_path / "BTC-USD").iterdir())][-1] == "BTC-USD_86400_2017-03-11_2017-11-19.json"
    assert len(list((tmp_path / "BTC-USD").iterdir())) == 3  # the shorter version of that page is gone
    offline = src.download_coinbase(None, tmp_path, ["BTC"], now=NOW)
    assert [p.name for p in offline.series[("BTC", "1d")]][-1].endswith("2017-11-19.json")
    with pytest.raises(FileNotFoundError, match="no Coinbase pages"):
        src.download_coinbase(None, tmp_path, ["ETH"], now=NOW)


def test_coinbase_page_with_wrong_rows_is_refused(world, tmp_path):
    routes = dict(world.routes)
    routes[COINBASE.format("ETH-USD")] = lambda r: httpx.Response(200, json=[[1, 2, 3]])
    with Server(routes).client() as c, pytest.raises(ValueError, match="unexpected candle row"):
        src.download_coinbase(c, tmp_path, ["ETH"], now=NOW, limiter=src.RateLimiter(0, sleep=Sleeps()))
    assert list((tmp_path / "ETH-USD").iterdir()) == []


# ============================================================================ loader additions


def binance_csv(path: Path, rows: list[list]) -> Path:
    path.write_text("\n".join(",".join(str(x) for x in r) for r in rows) + "\n")
    return path


def test_binance_grid_mode(tmp_path):
    t0 = 1_517_443_200_000  # 2018-02-01 00:00 UTC in ms
    hr = 3_600_000
    rows = [
        [t0, 10, 11, 9, 10.5, 1, t0 + hr - 1, 0, 5, 0, 0, 0],  # normal
        [t0 + hr, 10.5, 11, 10, 10.8, 1, t0 + hr + 1_200_000 - 1, 0, 5, 0, 0, 0],  # 20 minutes, kept
        [t0 + 2 * hr + 1_694_789, 10.8, 11, 10, 10.1, 1, t0 + 3 * hr + 1_694_788, 0, 5, 0, 0, 0],  # off grid
        [t0 + 3 * hr, 10.1, 11, 10, 10.2, 1, t0 + 3 * hr - 1000, 0, 5, 0, 0, 0],  # closes before it opens
        [t0 + 4 * hr, 10.2, 11, 10, 10.3, 1, t0 + 6 * hr - 1, 0, 5, 0, 0, 0],  # two hours long
        [t0 + 5 * hr, 10.3, 11, 10, 10.4, 1, t0 + 6 * hr - 1000, 0, 5, 0, 0, 0],  # 1 s short: not "short"
        [(t0 + 6 * hr) * 1000, 10.4, 11, 10, 10.6, 1, (t0 + 7 * hr) * 1000 - 1, 0, 5, 0, 0, 0],  # microseconds
    ]
    path = binance_csv(tmp_path / "BTCUSDT-1h-2018-02.csv", rows)
    got = load_binance_klines(path, interval="1h")
    expected = pd.DatetimeIndex([pd.Timestamp("2018-02-01 01:00", tz="UTC") + k * H for k in (0, 1, 5, 6)])
    assert list(got.index) == list(expected) and got.index.unit == "us"
    assert got["close"].tolist() == [10.5, 10.8, 10.4, 10.6]
    assert got.attrs["dropped_bad"] == 2 and got.attrs["dropped_off_grid"] == 1 and got.attrs["rows_read"] == 7
    assert got.attrs["off_grid_opens"] == ["2018-02-01T02:28:14.789000+00:00"]
    assert got.attrs["short_bars"] == [["2018-02-01T01:00:00+00:00", 1200]]
    plain = load_binance_klines(path)  # default mode is unchanged: the index is open + actual length
    assert pd.Timestamp("2018-02-01 01:20", tz="UTC") in plain.index and "dropped_off_grid" not in plain.attrs


def test_binance_grid_mode_errors(tmp_path):
    t0 = 1_517_443_200_000
    path = binance_csv(tmp_path / "x.csv", [[t0 + 5, 1, 1, 1, 1, 1, t0 + 3_600_004, 0, 1, 0, 0, 0]])
    with pytest.raises(ValueError, match="no valid rows"):
        load_binance_klines(path, interval="1h")
    with pytest.raises(ValueError, match="must be positive"):
        load_binance_klines(path, interval=pd.Timedelta(0))


def test_coinbase_candles_known_answer(tmp_path):
    day = 86_400
    t0 = 1_504_224_000  # 2017-09-01
    page1 = [[t0 + day, 9.5, 12.0, 10.0, 11.0, 5.5], [t0, 8.0, 10.5, 9.0, 10.0, 4.0]]  # newest first
    page2 = [[t0 + day, 9.0, 12.5, 10.0, 11.5, 6.0], [t0 + 2 * day, 1, 2, 3], [t0 + 3 * day, 1, 2, 1, 1, True],
             [t0 + 4 * day + 0.5, 1, 2, 1, 1, 1], [t0 + 5 * day, 1, 2, "1", 1, 1], [t0 + 6 * day, 5, 4, 4.5, 4.5, 1]]
    paths = []
    for i, page in enumerate((page1, page2)):
        p = tmp_path / "BTC-USD" / f"p{i}.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(page))
        paths.append(p)
    got = load_coinbase_candles(paths)
    assert list(got.index) == [pd.Timestamp("2017-09-02", tz="UTC"), pd.Timestamp("2017-09-03", tz="UTC")]
    first = got.iloc[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (9.0, 10.5, 8.0, 10.0, 4.0)
    assert got.iloc[1]["close"] == 11.5  # the later page's row wins
    assert got["trades"].isna().all()
    assert got.attrs == {"source": "BTC-USD (2 pages)", "rows_read": 8, "dropped_bad": 5, "dropped_duplicates": 1}


def test_coinbase_candles_errors(tmp_path):
    with pytest.raises(ValueError, match="no Coinbase pages"):
        load_coinbase_candles([])
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"message": "x"}))
    with pytest.raises(ValueError, match="must be a JSON list"):
        load_coinbase_candles([p])
    p.write_text("[]")
    with pytest.raises(ValueError, match="no valid rows"):
        load_coinbase_candles([p, p])


# ============================================================================ build


def test_parse_args():
    cfg = b.parse_args(["--sources", "kraken,binance"])  # the AGENTS.md command
    assert cfg.sources == ("kraken", "binance") and cfg.coins == ("BTC", "ETH") and cfg.intervals == ("1d", "1h")
    assert cfg.data_dir == Path("data") and cfg.report_dir == Path("reports/data") and not cfg.offline
    assert cfg.tolerance == 0.01
    d = b.parse_args([])
    assert d.sources == ("kraken", "binance", "coinbase")
    o = b.parse_args(["--offline", "--coins", "ETH,ETH", "--intervals", "1h", "--report-dir", "", "--tolerance", "0.02"])
    assert o.offline and o.coins == ("ETH",) and o.intervals == ("1h",) and o.report_dir is None and o.tolerance == 0.02


@pytest.mark.parametrize("argv", [["--sources", "kraken,tardis"], ["--coins", ""], ["--tolerance", "0"]])
def test_parse_args_rejects(argv, capsys):
    with pytest.raises(SystemExit):
        b.parse_args(argv)


def test_snapshot_id_rule():
    hashes = ["b" * 64, "a" * 64]
    expected = hashlib.sha256(("a" * 64 + "\n" + "b" * 64).encode()).hexdigest()[:16]
    assert b.compute_snapshot_id(hashes) == expected == b.compute_snapshot_id(reversed(hashes))


def test_git_state(tmp_path):
    assert b.git_state(tmp_path) == {"commit": "unknown", "lab_dirty": None}
    here = b.git_state()
    assert re.fullmatch(r"[0-9a-f]{40}", here["commit"]) and isinstance(here["lab_dirty"], bool)


def test_combine_counts_duplicates_across_files():
    idx = pd.date_range("2020-01-02", periods=3, freq="D", tz="UTC", name="ts")
    f1 = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx)
    f1.attrs = {"rows_read": 3, "dropped_bad": 1, "dropped_duplicates": 0, "short_bars": [["x", 5]]}
    f2 = pd.DataFrame({"close": [30.0, 4.0]}, index=idx[2:].append(idx[2:] + pd.Timedelta(days=1)))
    f2.attrs = {"rows_read": 2, "dropped_bad": 0, "dropped_duplicates": 1}
    out = b._combine([f2, f1])
    assert out["close"].tolist() == [1.0, 2.0, 3.0, 4.0]  # the duplicate keeps the later file's row
    assert out.attrs == {"files": 2, "dropped_duplicates": 2, "rows_read": 5, "dropped_bad": 1,
                         "dropped_off_grid": 0, "off_grid_opens": [], "short_bars": [["x", 5]]}


def cfg_for(tmp_path, **kw) -> b.BuildConfig:
    kw.setdefault("report_dir", tmp_path / "reports")
    return b.BuildConfig(data_dir=tmp_path / "data", **kw)


@pytest.fixture(scope="module")
def built(world, tmp_path_factory):
    """One online build of the whole world (all sources, coins and intervals)."""
    root = tmp_path_factory.mktemp("built")
    server = world.server()
    with server.client() as c:
        result = b.build(cfg_for(root), client=c, now=NOW)
    return root, result, server


def test_build_writes_catalog_snapshot_and_report(built, world):
    root, result, server = built
    data = root / "data"
    snap = json.loads((data / "catalog" / cat.SNAPSHOT_FILE).read_text())
    assert result["publish"] == "new" and result["snapshot_id"] == snap["snapshot_id"] == cat.snapshot_id(data / "catalog")
    assert snap["schema"] == "osprey.snapshot/1" and snap["created"] == "2017-11-15T12:00:00Z"
    all_files = [f for s in snap["sources"].values() for f in s["files"]]
    assert snap["snapshot_id"] == b.compute_snapshot_id(f["sha256"] for f in all_files)
    for f in all_files:  # every recorded hash is the file's hash, paths relative to the data dir
        assert hashlib.sha256((data / f["path"]).read_bytes()).hexdigest() == f["sha256"]
        assert (data / f["path"]).stat().st_size == f["bytes"]
    assert len(snap["sources"]["kraken"]["files"]) == 6 and len(snap["sources"]["binance"]["files"]) == 24
    assert len(snap["sources"]["coinbase"]["files"]) == 6
    assert [s["bar_type"] for s in snap["series"]] == [
        "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL", "BTC/USD.KRAKEN-1-HOUR-LAST-EXTERNAL",
        "ETH/USD.KRAKEN-1-DAY-LAST-EXTERNAL", "ETH/USD.KRAKEN-1-HOUR-LAST-EXTERNAL",
        "BTCUSDT.BINANCE-1-DAY-LAST-EXTERNAL", "BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL",
        "ETHUSDT.BINANCE-1-DAY-LAST-EXTERNAL", "ETHUSDT.BINANCE-1-HOUR-LAST-EXTERNAL",
        "BTC-USD.COINBASE-1-DAY-LAST-EXTERNAL", "ETH-USD.COINBASE-1-DAY-LAST-EXTERNAL",
    ]
    kraken_h = next(s for s in snap["series"] if s["bar_type"] == "BTC/USD.KRAKEN-1-HOUR-LAST-EXTERNAL")
    assert kraken_h["rows"] == DAYS * 24 - 3 and kraken_h["gaps"] == 1 and kraken_h["missing_bars"] == 3
    assert kraken_h["start"] == "2017-08-01T01:00:00+00:00" and kraken_h["end"] == "2017-11-01T00:00:00+00:00"
    assert all(set(s) >= {"instrument", "source", "bar", "start", "end", "rows", "gaps"} for s in snap["series"])
    # every request went to an allowed host, with the generic User-Agent
    assert {httpx.URL(u).host for _, u, _ in server.log} <= src.ALLOWED_HOSTS
    assert {h["user-agent"] for _, _, h in server.log} == {"strategy-lab/0.1"}
    assert not (data / b.STAGING).exists()


def test_build_round_trip_equals_the_source_data(built, world):
    root, _, _ = built
    cd = root / "data" / "catalog"
    snap = json.loads((cd / cat.SNAPSHOT_FILE).read_text())
    assert all(r["exact"] and r["max_price_ulps_vs_source"] <= 1 for r in snap["checks"]["round_trip"].values())
    got = cat.load_bars("BTC/USD.KRAKEN", "1h", catalog_dir=cd)
    src_h = world.kraken_hourly["BTC"]
    assert list(got.index) == list(src_h.index + H)  # open time + 1 hour = close time
    assert np.abs(got["close"].to_numpy() - src_h["close"].to_numpy()).max() <= np.spacing(src_h["close"].max())
    assert got.attrs["snapshot_id"] == snap["snapshot_id"]
    daily = cat.load_bars("ETH-USD.COINBASE", "1d", catalog_dir=cd)
    assert len(daily) == DAYS and daily.index[0] == pd.Timestamp("2017-08-02", tz="UTC")


def test_build_quality_policy_and_checks(built):
    root, _, _ = built
    snap = json.loads((root / "data" / "catalog" / cat.SNAPSHOT_FILE).read_text())
    load = snap["checks"]["loading"]["BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"]
    assert load["dropped_bad"] == 1 and load["dropped_off_grid"] == 1 and load["dropped_zero_volume"] == 1
    assert len(load["short_bars"]) == 1 and load["files"] == 3 and load["rows_read"] == DAYS * 24 + 1
    rows = next(s["rows"] for s in snap["series"] if s["bar_type"] == "BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL")
    assert rows == DAYS * 24 - 2  # the bad bar and the zero-volume bar are gaps now; the short bar stays
    assert snap["checks"]["quality"]["BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"]["missing_bars"] == 2
    dh = snap["checks"]["daily_vs_hourly"]
    assert dh["BTC/USD.KRAKEN"]["mismatches"] == {"open": 0, "high": 0, "low": 0, "close": 0}
    assert dh["BTCUSDT.BINANCE"]["mismatches"]["close"] >= 1  # the outlier day only exists in the daily file
    cc = snap["checks"]["cross_check"]["BTC"]
    flagged = [o for o in cc["outliers"] if o["day"] == "2017-09-15"]
    assert len(flagged) == 1 and set(flagged[0]["pairs"]) == {"binance/coinbase", "binance/kraken"}
    assert flagged[0]["hourly_bars"] == {"binance": 24, "kraken": 24}
    assert len(cc["outliers"]) == 1 and snap["checks"]["cross_check"]["ETH"]["outliers"] == []
    assert all(r["aligned"] for c in snap["checks"]["alignment"].values() for i in c.values() for r in i.values())
    # the train window is 2017-01-01..2022-12-31: these 92 days lie inside it, starting late and ending early
    cov = snap["checks"]["train_coverage"]["BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL"]
    assert cov["present"] == DAYS and cov["first"] == "2017-08-02T00:00:00+00:00" and cov["missing_inside"] == 0
    assert cov["late_start_bars"] == (pd.Timestamp("2017-08-02") - pd.Timestamp("2017-01-02")).days
    assert cov["early_end_bars"] == (pd.Timestamp("2023-01-01") - pd.Timestamp("2017-11-01")).days
    assert not cov["covered"] and not cov["complete"]


def test_build_report_has_every_section(built):
    root, result, _ = built
    text = Path(result["report"]).read_text()
    assert Path(result["report"]).name == "2017-11-15.md"
    for heading in ["## 1. Sources", "## 2. Coverage", "## 3. Gaps", "## 4. Bad ticks", "## 5. Daily bars",
                    "## 6. Cross-check", "## 6a. Time alignment", "## 7. Catalog round trip", "## 8. Open items"]:
        assert heading in text
    assert result["snapshot_id"] in text and "NOT the whole-archive SHA-256" in text
    assert "| 2017-09-15 |" in text and "binance 24, kraken 24" in text
    assert "cbBTC/USDC" in text and "not estimated" in text
    assert "off-grid opens dropped: 2017-09-02T16:28:00+00:00" in text


def test_offline_rebuild_is_unchanged_and_uses_no_network(built, monkeypatch):
    root, result, _ = built
    monkeypatch.setattr(src, "make_client", lambda *a, **k: pytest.fail("offline build made a client"))
    again = b.build(cfg_for(root, offline=True), now=datetime(2017, 11, 16, tzinfo=UTC))
    assert again["publish"] == "unchanged" and again["snapshot_id"] == result["snapshot_id"]
    assert again["created"] == result["created"]  # the existing snapshot is kept as it was


def test_a_changed_raw_file_makes_a_new_snapshot_and_archives_the_old(world, tmp_path):
    with world.server().client() as c:
        first = b.build(cfg_for(tmp_path, sources=("kraken", "coinbase"), coins=("BTC",)), client=c, now=NOW)
    page = tmp_path / "data" / "raw" / "coinbase" / "BTC-USD" / "BTC-USD_86400_2017-03-11_2017-11-14.json"
    rows = json.loads(page.read_text())
    rows[0][5] += 1.0  # one volume corrected upstream
    page.write_text(json.dumps(rows))
    second = b.build(cfg_for(tmp_path, sources=("kraken", "coinbase"), coins=("BTC",), offline=True), now=NOW)
    assert second["snapshot_id"] != first["snapshot_id"]
    archived = tmp_path / "data" / "snapshots" / first["snapshot_id"]
    assert second["publish"] == f"replaced {first['snapshot_id']} (archived to {archived})"
    assert cat.snapshot_id(archived) == first["snapshot_id"]
    assert cat.snapshot_id(tmp_path / "data" / "catalog") == second["snapshot_id"]
    assert len(cat.load_bars("BTC/USD.KRAKEN", "1d", catalog_dir=archived)) == DAYS  # the old one still loads


def test_snapshot_is_never_overwritten_in_place(world, tmp_path):
    cfg = cfg_for(tmp_path, sources=("kraken",), coins=("ETH",), intervals=("1d",))
    with world.server().client() as c:
        first = b.build(cfg, client=c, now=NOW)
    snap_path = tmp_path / "data" / "catalog" / cat.SNAPSHOT_FILE
    snap = json.loads(snap_path.read_text())
    snap["content_sha256"] = "0" * 64  # as if the bars of this snapshot had been built by other code
    snap_path.write_text(json.dumps(snap))
    offline = cfg_for(tmp_path, sources=("kraken",), coins=("ETH",), intervals=("1d",), offline=True)
    with pytest.raises(b.SnapshotConflict, match="same raw files but different bars"):
        b.build(offline, now=NOW)
    snap_path.unlink()
    with pytest.raises(b.SnapshotConflict, match="exists without SNAPSHOT.json"):
        b.build(offline, now=NOW)
    snap_path.write_text(json.dumps({"snapshot_id": "fedcba9876543210"}))
    (tmp_path / "data" / "snapshots" / "fedcba9876543210").mkdir(parents=True)
    with pytest.raises(b.SnapshotConflict, match="refusing to overwrite an archived snapshot"):
        b.build(offline, now=NOW)
    assert first["publish"] == "new"


def test_single_source_build_skips_the_cross_check(world, tmp_path):
    with world.server().client() as c:
        result = b.build(cfg_for(tmp_path, sources=("binance",), intervals=("1h",)), client=c, now=NOW)
    assert result["checks"]["cross_check"] == {} and result["checks"]["alignment"] == {}
    assert result["checks"]["daily_vs_hourly"] == {}
    text = Path(result["report"]).read_text()
    assert "Not run: fewer than two sources with daily bars." in text and "Not run: fewer than two sources." in text


def test_a_source_on_another_clock_stops_the_build():
    idx = pd.date_range("2020-01-01 01:00", periods=300, freq="h", tz="UTC", name="ts")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(9).normal(0, 0.01, 300)))
    frame = pd.DataFrame({"open": close, "high": close * 1.001, "low": close * 0.999, "close": close,
                          "volume": 1.0}, index=idx)
    shifted = frame.copy()
    shifted.index = shifted.index + H  # labelled one hour late: bar OPEN time used as if it were the close
    series = [b.Series("kraken", "BTC", "1h", frame), b.Series("binance", "BTC", "1h", shifted)]
    with pytest.raises(b.DataQualityError, match="agree best when shifted by"):
        b.run_checks(series, 0.01)


def test_round_trip_mismatch_stops_the_build(world, tmp_path, monkeypatch):
    real = cat.load_bars

    def off_by_one_tick(*a, **k):
        got = real(*a, **k)
        got.iloc[0, 0] += 0.01
        return got

    monkeypatch.setattr(cat, "load_bars", off_by_one_tick)
    leftover = tmp_path / "data" / b.STAGING / "leftover.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("from a crashed build")  # a leftover staging dir is cleared, not reused
    with world.server().client() as c, pytest.raises(RuntimeError, match="round trip differs"):
        b.build(cfg_for(tmp_path, sources=("kraken",), coins=("BTC",), intervals=("1d",)), client=c, now=NOW)
    assert not (tmp_path / "data" / "catalog").exists() and not leftover.exists()


def test_build_makes_and_closes_its_own_client(world, tmp_path, monkeypatch):
    made = []

    def make(*a, **k):
        made.append(world.server().client())
        return made[-1]

    monkeypatch.setattr(src, "make_client", make)
    result = b.build(cfg_for(tmp_path, sources=("kraken",), coins=("BTC",), intervals=("1d",), report_dir=None), now=NOW)
    assert len(made) == 1 and made[0].is_closed and "report" not in result


def test_main_and_module_entry_point(built, capsys, monkeypatch, tmp_path):
    root, result, _ = built
    argv = ["--offline", "--data-dir", str(root / "data"), "--report-dir", str(root / "main-reports")]
    assert b.main(argv) == 0
    out = capsys.readouterr().out
    assert f"snapshot {result['snapshot_id']} (unchanged)" in out and "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL" in out
    assert "report: " in out and (root / "main-reports" / "2017-11-15.md").is_file()
    monkeypatch.chdir(tmp_path)  # regression: --report-dir '' once became Path('.') and wrote the report here
    assert b.main([*argv[:3], "--report-dir", ""]) == 0
    assert "report:" not in capsys.readouterr().out and list(tmp_path.iterdir()) == []
    monkeypatch.setattr("sys.argv", ["lab.data.build", "--help"])
    with warnings.catch_warnings(), pytest.raises(SystemExit) as exc:
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: the module is already imported by this test
        runpy.run_module("lab.data.build", run_name="__main__")
    assert exc.value.code == 0 and "--offline" in capsys.readouterr().out


# ============================================================================ report details


def test_report_lists_are_truncated_and_values_formatted():
    assert rep._list([]) == "none"
    assert rep._list(list(range(60))).endswith("... (+10 more in SNAPSHOT.json)")
    assert rep._fmt(None) == "n/a" and rep._fmt(True) == "yes" and rep._fmt(False) == "no"
    assert rep._fmt(0.123456) == "0.1235" and rep._fmt(7) == "7"
    assert rep._price(13240.5) == "13240.5" and rep._price(None) == "n/a"
    assert rep._pct(0.0123) == "+1.230%" and rep._pct(None) == "n/a"


def test_report_renders_optional_details(built):
    root, result, _ = built
    snap = json.loads((root / "data" / "catalog" / cat.SNAPSHOT_FILE).read_text())
    snap["sources"]["binance"]["details"]["missing"] = ["BTCUSDT-1d-2017-11"]
    snap["checks"]["cross_check"]["BTC"]["outliers"] = [
        {"day": "2017-09-15", "values": {"binance": 1.0, "coinbase": 2.0}, "pairs": {"binance/coinbase": -0.5}}
    ]
    q = snap["checks"]["quality"]["ETH/USD.KRAKEN-1-HOUR-LAST-EXTERNAL"]
    q["extreme_moves_top"] = [{"ts": "2017-05-07T23:00:00+00:00", "log": -1.0872, "sigma": 0.01, "k": 98.0}]
    q["extreme_wicks_top"] = [{"ts": "2021-02-22T15:00:00+00:00", "log": 0.9017, "sigma": 0.01, "k": 80.7}]
    q["longest_stale"] = {"from": "2015-08-11T09:00:00+00:00", "to": "2015-08-11T14:00:00+00:00", "unchanged_bars": 5}
    snap["checks"]["train_coverage"]["BTC/USD.KRAKEN-1-HOUR-LAST-EXTERNAL"].update(
        missing_inside=3, gaps=[{"after": "2017-08-21T20:00:00+00:00", "before": "2017-08-22T00:00:00+00:00", "missing": 3}])
    text = rep.render_report(snap)
    assert "Missing months: BTCUSDT-1d-2017-11" in text
    assert "| 2017-09-15 | 1.0 | 2.0 | n/a | binance/coinbase -50.000% | n/a |" in text
    assert ("- `ETH/USD.KRAKEN-1-HOUR-LAST-EXTERNAL`: largest moves: 2017-05-07T23:00:00+00:00 (log -1.0872, 98.0 "
            "sigma); largest wicks: 2021-02-22T15:00:00+00:00 (log 0.9017, 80.7 sigma); longest stale close: 5 bars "
            "unchanged, 2015-08-11T09:00:00+00:00 -> 2015-08-11T14:00:00+00:00") in text
    assert ("- `BTC/USD.KRAKEN-1-HOUR-LAST-EXTERNAL`: 3 bars in 1 gaps: 2017-08-21T20:00:00+00:00 -> "
            "2017-08-22T00:00:00+00:00 (3)") in text
