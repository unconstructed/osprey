"""Downloads from the free data sources: the only code in the lab that talks to the network.

Every request goes through :func:`fetch`, which refuses any URL that is not ``https`` on one of
``ALLOWED_HOSTS`` (AGENTS.md: no network traffic except the data sources in ``lab/data/``), never follows a
redirect (a redirect could leave the allow-list), sends the generic ``User-Agent: strategy-lab/0.1``, retries
429 and 5xx answers and transport errors with exponential backoff (``Retry-After`` honoured up to a cap), and
caps the body size before reading it. Nothing here sends anything but GET and HEAD requests.

Sources (raw files land in ``<data>/raw/<source>/`` and each one is SHA-256 hashed for the snapshot):

- **kraken**: the official full OHLCVT history, published as one zip split into parts
  (``Kraken_OHLCVT_Full.zip.part00`` ..). The part names come from Kraken's ``OHLCVT_Full_PARTS_SHA256SUMS.txt``
  (stored too). We never download the ~9.5 GB archive: :class:`MultiPartHTTPReader` makes the concatenated
  parts look like one seekable file through HTTP range requests, and ``zipfile`` reads the central directory
  and only the members named EXACTLY ``XBTUSD_1440.csv`` etc. (``AIXBTUSD_1440.csv`` must not match).
  ``zipfile`` checks each member's CRC-32 when it is read to the end. The whole-archive SHA-256 in the sums
  file can NOT be checked (we never hold the archive); the part ETags are recorded instead, and every range
  answer must carry the ETag seen at the start, so a part replaced mid-read is caught.
- **binance**: monthly kline zips from data.binance.vision, each verified against its ``.CHECKSUM`` file
  (SHA-256) before it is written; at most ``BINANCE_WORKERS`` requests at a time.
- **coinbase**: public REST daily candles, 300 per request, at most ~3 requests per second; raw JSON pages
  are stored as received. Only complete candles are requested (the current day is never fetched).

Files already on disk that still verify (Binance zip against its stored checksum, Kraken members against the
recorded CRC-32 and SHA-256, complete Coinbase pages) are not downloaded again. ``offline=True`` builds use
only what is on disk and verify it the same way.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
import zlib
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

ALLOWED_HOSTS = frozenset(
    {"data.binance.vision", "assets.kraken.com", "api.kraken.com", "api.exchange.coinbase.com"}
)
USER_AGENT = "strategy-lab/0.1"
TIMEOUT = httpx.Timeout(60.0, connect=20.0)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

COINS = ("BTC", "ETH")
INTERVALS = ("1d", "1h")


class DisallowedHostError(ValueError):
    """A URL outside the data-source allow-list (or not https)."""


class DownloadError(RuntimeError):
    """A request failed for good (unexpected status, too large, retries exhausted)."""


class NotFoundError(DownloadError):
    """HTTP 404: the file does not exist at the source."""


class ChecksumError(ValueError):
    """Downloaded or stored bytes do not match their published or recorded checksum."""


# --------------------------------------------------------------------------- the single request path


def check_url(url: str | httpx.URL) -> httpx.URL:
    """Return ``url`` parsed, or raise :class:`DisallowedHostError` unless it is https on an allowed host."""
    parsed = httpx.URL(str(url))
    if parsed.scheme != "https":
        raise DisallowedHostError(f"only https is allowed: {url}")
    if parsed.userinfo:
        raise DisallowedHostError(f"credentials in a URL are not allowed: {parsed.host}")
    if parsed.host not in ALLOWED_HOSTS or parsed.port not in (None, 443):
        raise DisallowedHostError(f"host not on the data-source allow-list: {parsed.host}")
    return parsed


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """An ``httpx.Client`` with the generic User-Agent and timeouts (``transport`` is for tests)."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, transport=transport, follow_redirects=False
    )


@dataclass
class Retry:
    """Retry policy: ``max_retries`` after the first try, waits of ``backoff * 2**k`` seconds (or the
    server's ``Retry-After``), each capped at ``max_wait``. ``sleep`` is injectable for tests."""

    max_retries: int = 5
    backoff: float = 1.0
    max_wait: float = 60.0
    sleep: Callable[[float], None] = time.sleep

    def wait(self, attempt: int, retry_after: str | None) -> None:
        delay = self.backoff * 2**attempt
        if retry_after is not None and retry_after.strip().isdigit():
            delay = float(retry_after.strip())
        self.sleep(min(delay, self.max_wait))


class RateLimiter:
    """At most one request per ``min_interval`` seconds (thread-safe)."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep
        self._next = float("-inf")
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self._next:
                self._sleep(self._next - now)
                now = self._next
            self._next = now + self.min_interval


@dataclass(frozen=True)
class Fetched:
    """One answered request: final status, headers and the (size-capped) body."""

    url: str
    status: int
    headers: httpx.Headers
    content: bytes


def fetch(
    client: httpx.Client,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    expect: Iterable[int] = (200,),
    max_bytes: int = 64 << 20,
    retry: Retry | None = None,
    limiter: RateLimiter | None = None,
) -> Fetched:
    """The one function every download goes through (see the module docstring).

    Raises :class:`DisallowedHostError` before any traffic for a URL off the allow-list,
    :class:`NotFoundError` on 404, and :class:`DownloadError` on any other unexpected status (a redirect
    included), a body over ``max_bytes`` (checked against Content-Length before reading, and while reading),
    or when retries of 429/5xx/transport errors run out.
    """
    if method not in ("GET", "HEAD"):
        raise ValueError(f"only GET and HEAD requests are allowed, not {method}")
    parsed = check_url(url)
    retry = retry or Retry()
    expected = frozenset(expect)
    last: str = ""
    for attempt in range(retry.max_retries + 1):
        if limiter is not None:
            limiter.wait()
        retry_after = None
        try:
            with client.stream(method, parsed, headers=headers, params=params, follow_redirects=False) as r:
                if r.status_code in RETRY_STATUSES:
                    last, retry_after = f"HTTP {r.status_code}", r.headers.get("retry-after")
                else:
                    return _read(r, str(parsed), expected, max_bytes)
        except httpx.TransportError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < retry.max_retries:
            retry.wait(attempt, retry_after)
    raise DownloadError(f"{parsed}: giving up after {retry.max_retries + 1} tries ({last})")


def _read(r: httpx.Response, url: str, expected: frozenset[int], max_bytes: int) -> Fetched:
    if r.status_code == 404:
        raise NotFoundError(f"{url}: HTTP 404")
    if r.status_code not in expected:
        raise DownloadError(f"{url}: HTTP {r.status_code}, expected {sorted(expected)}")
    length = r.headers.get("content-length")
    if length is not None and r.request.method == "GET" and int(length) > max_bytes:
        raise DownloadError(f"{url}: {length} bytes is over the {max_bytes} byte limit")
    body = bytearray()
    for chunk in r.iter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise DownloadError(f"{url}: body over the {max_bytes} byte limit")
    return Fetched(url, r.status_code, r.headers, bytes(body))


# --------------------------------------------------------------------------- files and hashes


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a temporary file and a rename (no half-written raw files)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass(frozen=True)
class RawFile:
    """A raw file of the snapshot: absolute ``path``, its SHA-256 and size."""

    path: Path
    sha256: str
    bytes: int

    @classmethod
    def of(cls, path: Path) -> RawFile:
        return cls(path, sha256_file(path), path.stat().st_size)


@dataclass
class SourceFiles:
    """What one source contributed: every hashed raw file, the files behind each ``(coin, interval)``
    series, and notes for the snapshot and the quality report."""

    source: str
    files: list[RawFile] = field(default_factory=list)
    series: dict[tuple[str, str], list[Path]] = field(default_factory=dict)
    notes: dict = field(default_factory=dict)


def _check_selection(coins: Sequence[str], intervals: Sequence[str]) -> None:
    bad = [c for c in coins if c not in COINS] + [i for i in intervals if i not in INTERVALS]
    if bad or not coins or not intervals:
        raise ValueError(f"coins must be from {COINS} and intervals from {INTERVALS}; got {coins}, {intervals}")


# --------------------------------------------------------------------------- kraken


KRAKEN_BASE = "https://assets.kraken.com/marketing/institutions/"
KRAKEN_SUMS = "OHLCVT_Full_PARTS_SHA256SUMS.txt"
KRAKEN_PART_RE = re.compile(r"Kraken_OHLCVT_Full\.zip\.part(\d{2})")
KRAKEN_PAIRS = {"BTC": "XBTUSD", "ETH": "ETHUSD"}
KRAKEN_MINUTES = {"1d": 1440, "1h": 60}
KRAKEN_MANIFEST = "MANIFEST.json"
KRAKEN_PROVENANCE = "_provenance.json"  # our own record; not a source file, not hashed into the snapshot


def kraken_member(coin: str, interval: str) -> str:
    """Exact archive member name of a series, e.g. ``XBTUSD_1440.csv``."""
    return f"{KRAKEN_PAIRS[coin]}_{KRAKEN_MINUTES[interval]}.csv"


def parse_sha256sums(text: str) -> dict[str, str]:
    """``sha256sum`` output -> {file name: hex digest}; any other line is an error."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(\S+)\s*", line)
        if match is None:
            raise ChecksumError(f"not a sha256sum line: {line[:80]!r}")
        out[match.group(2)] = match.group(1).lower()
    if not out:
        raise ChecksumError("checksum file lists no files")
    return out


def kraken_part_names(sums: dict[str, str]) -> list[str]:
    """The archive part names listed in the sums file, in order; they must be part00, part01, .. with no hole."""
    parts = sorted(n for n in sums if KRAKEN_PART_RE.fullmatch(n))
    numbers = [int(KRAKEN_PART_RE.fullmatch(n).group(1)) for n in parts]
    if not parts or numbers != list(range(len(parts))):
        raise DownloadError(f"unexpected archive parts in {KRAKEN_SUMS}: {parts}")
    return parts


class MultiPartHTTPReader(io.RawIOBase):
    """Read-only, seekable view of the concatenation of ``urls`` through HTTP range requests.

    Sizes and ETags come from a HEAD of each part. Every range answer must be ``206`` with the exact
    ``Content-Range`` asked for, the exact number of bytes, and (when the HEAD had one) the part's original
    ETag, so a server that ignores ``Range`` or a part replaced during the read fails loudly.
    """

    def __init__(self, client: httpx.Client, urls: Sequence[str], retry: Retry | None = None) -> None:
        super().__init__()
        self.client, self.urls, self.retry = client, list(urls), retry
        self.parts: list[dict] = []
        for url in self.urls:
            head = fetch(client, url, method="HEAD", retry=retry)
            length = head.headers.get("content-length")
            if length is None or not length.isdigit():
                raise DownloadError(f"{url}: HEAD gave no usable Content-Length")
            self.parts.append(
                {
                    "url": url,
                    "bytes": int(length),
                    "etag": head.headers.get("etag"),
                    "last_modified": head.headers.get("last-modified"),
                }
            )
        self.total = sum(p["bytes"] for p in self.parts)
        self.pos = 0
        self.requests = 0
        self.fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.total}[whence]
        if base + offset < 0:
            raise ValueError("negative seek position")
        self.pos = base + offset
        return self.pos

    def readinto(self, buffer) -> int:
        start = self.pos
        end = min(start + len(buffer), self.total)
        if end <= start:
            return 0
        out = bytearray()
        offset = 0
        for part in self.parts:
            lo, hi = max(start, offset), min(end, offset + part["bytes"])
            if lo < hi:
                out += self._range(part, lo - offset, hi - offset - 1)
            offset += part["bytes"]
        buffer[: len(out)] = out
        self.pos += len(out)
        return len(out)

    def _range(self, part: dict, first: int, last: int) -> bytes:
        got = fetch(
            self.client,
            part["url"],
            headers={"Range": f"bytes={first}-{last}", "Accept-Encoding": "identity"},
            expect=(206,),
            max_bytes=last - first + 1,
            retry=self.retry,
        )
        self.requests += 1
        want = f"bytes {first}-{last}/{part['bytes']}"
        if got.headers.get("content-range") != want or len(got.content) != last - first + 1:
            raise DownloadError(
                f"{part['url']}: asked for {want}, got {got.headers.get('content-range')} "
                f"with {len(got.content)} bytes"
            )
        etag = got.headers.get("etag")
        if part["etag"] is not None and etag != part["etag"]:
            raise DownloadError(f"{part['url']}: ETag changed during the read ({part['etag']} -> {etag})")
        self.fetched += len(got.content)
        return got.content


def extract_members(
    archive: io.RawIOBase, names: Sequence[str]
) -> tuple[dict[str, tuple[bytes, zipfile.ZipInfo]], int]:
    """Read the members called exactly ``names`` (each must appear exactly once) from a zip; also return the
    number of members in the archive.

    ``zipfile`` checks the CRC-32 of each member as it reads it to the end (``BadZipFile`` on a mismatch, and
    ``EOFError`` if the data ends early). Nothing is written to disk and member paths are never used as paths.
    """
    with zipfile.ZipFile(io.BufferedReader(archive, buffer_size=1 << 20)) as zf:
        infos = zf.infolist()
        out = {}
        for name in names:
            hits = [i for i in infos if i.filename == name]
            if len(hits) != 1:
                raise DownloadError(f"archive has {len(hits)} members named exactly {name!r} (need 1)")
            info = hits[0]
            with zf.open(info) as fh:
                data = fh.read()  # zipfile raises unless exactly file_size bytes with the right CRC-32 came out
            out[name] = (data, info)
    return out, len(infos)


def _verify_kraken_local(raw_dir: Path, names: Sequence[str]) -> dict | None:
    """The stored provenance if every member file is on disk and matches its recorded CRC-32 and SHA-256;
    None when anything is missing. A file that exists but no longer matches raises :class:`ChecksumError`."""
    prov_path = raw_dir / KRAKEN_PROVENANCE
    if not prov_path.is_file():
        return None
    prov = json.loads(prov_path.read_text())
    for name in names:
        path, rec = raw_dir / name, prov.get("members", {}).get(name)
        if rec is None or not path.is_file():
            return None
        data = path.read_bytes()
        if f"{zlib.crc32(data):08x}" != rec["crc32"] or sha256_bytes(data) != rec["sha256"]:
            raise ChecksumError(f"{path}: no longer matches the CRC-32/SHA-256 recorded when it was extracted")
    if not (raw_dir / KRAKEN_SUMS).is_file():
        return None
    return prov


def download_kraken(
    client: httpx.Client | None,
    raw_dir: Path,
    coins: Sequence[str],
    intervals: Sequence[str],
    *,
    retry: Retry | None = None,
    now: datetime | None = None,
) -> SourceFiles:
    """Kraken members for the selected series plus ``MANIFEST.json`` and the sums file.

    ``client=None`` means offline: use and verify the files on disk. Online, the sums file is fetched and
    the parts' HEADs compared with the provenance on disk; members are re-extracted only when a file is
    missing or the archive changed (other ETags or sizes).
    """
    _check_selection(coins, intervals)
    raw_dir.mkdir(parents=True, exist_ok=True)
    series = {(c, i): raw_dir / kraken_member(c, i) for c in coins for i in intervals}
    names = sorted({p.name for p in series.values()} | {KRAKEN_MANIFEST})
    local = _verify_kraken_local(raw_dir, names)
    if client is None:
        if local is None:
            raise FileNotFoundError(f"offline build: Kraken files or {KRAKEN_PROVENANCE} missing in {raw_dir}")
        prov, action = local, "offline: verified files on disk against the recorded CRC-32 and SHA-256"
    else:
        sums_text = fetch(client, KRAKEN_BASE + KRAKEN_SUMS, max_bytes=1 << 16, retry=retry).content
        sums = parse_sha256sums(sums_text.decode("utf-8"))
        write_atomic(raw_dir / KRAKEN_SUMS, sums_text)
        reader = MultiPartHTTPReader(client, [KRAKEN_BASE + n for n in kraken_part_names(sums)], retry)
        same_archive = local is not None and [
            (p["url"], p["bytes"], p["etag"]) for p in local["archive"]["parts"]
        ] == [(p["url"], p["bytes"], p["etag"]) for p in reader.parts]
        if same_archive:
            prov, action = local, "online: archive unchanged (same part ETags and sizes); files on disk verified"
        else:
            got, n_members = extract_members(reader, names)
            members = {}
            for name, (data, info) in got.items():
                write_atomic(raw_dir / name, data)
                members[name] = {
                    "crc32": f"{info.CRC:08x}",
                    "sha256": sha256_bytes(data),
                    "file_size": info.file_size,
                    "compress_size": info.compress_size,
                    "date_time": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*info.date_time),
                }
            prov = {
                "extracted_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
                "archive": {
                    "parts": reader.parts,
                    "total_bytes": reader.total,
                    "members_in_archive": n_members,
                    "range_requests": reader.requests,
                    "bytes_fetched": reader.fetched,
                    "published_sha256": {n: sums[n] for n in kraken_part_names(sums)},
                },
                "members": members,
            }
            write_atomic(raw_dir / KRAKEN_PROVENANCE, json.dumps(prov, indent=2).encode())
            action = "online: members extracted from the archive by HTTP range reads"
    out = SourceFiles("kraken")
    out.files = [RawFile.of(raw_dir / n) for n in [*names, KRAKEN_SUMS]]
    out.series = {key: [path] for key, path in series.items()}
    manifest = json.loads((raw_dir / KRAKEN_MANIFEST).read_text())
    out.notes = {
        "action": action,
        "verified": "member CRC-32 (zipfile, on extraction) and member size; NOT the whole-archive SHA-256 "
        "(the archive is never held, only ranges of it are read)",
        "archive": prov["archive"],
        "members": prov["members"],
        "extracted_at": prov["extracted_at"],
        "manifest": manifest,
    }
    return out


# --------------------------------------------------------------------------- binance


BINANCE_URL = "https://data.binance.vision/data/spot/monthly/klines/{sym}/{iv}/{name}"
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
BINANCE_FIRST_MONTH = (2017, 8)
BINANCE_WORKERS = 4


def month_range(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    """Every (year, month) from ``first`` to ``last`` inclusive."""
    out = []
    year, month = first
    while (year, month) <= last:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def last_complete_month(now: datetime) -> tuple[int, int]:
    """The month before ``now``'s month (UTC)."""
    now = now.astimezone(UTC)
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def verify_checksum(data: bytes, checksum_text: str, filename: str) -> str:
    """SHA-256 of ``data`` if it matches the one ``.CHECKSUM`` line for ``filename``; else ChecksumError."""
    listed = parse_sha256sums(checksum_text)
    if list(listed) != [filename]:
        raise ChecksumError(f"{filename}: checksum file is for {sorted(listed)}")
    digest = sha256_bytes(data)
    if digest != listed[filename]:
        raise ChecksumError(f"{filename}: SHA-256 {digest} does not match the published {listed[filename]}")
    return digest


def _binance_month(
    client: httpx.Client | None, folder: Path, sym: str, iv: str, ym: tuple[int, int], retry: Retry | None
) -> tuple[str, Path | None]:
    """Make sure one monthly zip is on disk and verified. Returns (status, zip path or None if missing)."""
    name = f"{sym}-{iv}-{ym[0]:04d}-{ym[1]:02d}.zip"
    path, check = folder / name, folder / (name + ".CHECKSUM")
    if path.is_file() and check.is_file():
        verify_checksum(path.read_bytes(), check.read_text(), name)
        return "verified on disk", path
    if client is None:
        return "missing", None
    url = BINANCE_URL.format(sym=sym, iv=iv, name=name)
    try:
        check_text = fetch(client, url + ".CHECKSUM", max_bytes=4096, retry=retry).content
    except NotFoundError:
        return "missing", None
    data = fetch(client, url, max_bytes=256 << 20, retry=retry).content
    verify_checksum(data, check_text.decode("utf-8"), name)
    write_atomic(check, check_text)
    write_atomic(path, data)
    return "downloaded and verified", path


def download_binance(
    client: httpx.Client | None,
    raw_dir: Path,
    coins: Sequence[str],
    intervals: Sequence[str],
    *,
    now: datetime,
    retry: Retry | None = None,
    workers: int = BINANCE_WORKERS,
) -> SourceFiles:
    """Monthly kline zips from 2017-08 to the last complete month, each checked against its ``.CHECKSUM``.

    Offline (``client=None``) the same months are looked for on disk. A month that does not exist (404, or
    not on disk offline) is listed in ``notes["missing"]``, never filled.
    """
    _check_selection(coins, intervals)
    months = month_range(BINANCE_FIRST_MONTH, last_complete_month(now))
    jobs = [(c, i, ym) for c in coins for i in intervals for ym in months]

    def run(job):
        coin, iv, ym = job
        sym = BINANCE_SYMBOLS[coin]
        return job, _binance_month(client, raw_dir / sym / iv, sym, iv, ym, retry)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, jobs))
    out = SourceFiles("binance")
    status_counts: dict[str, int] = {}
    missing = []
    for (coin, iv, ym), (status, path) in results:
        status_counts[status] = status_counts.get(status, 0) + 1
        if path is None:
            missing.append(f"{BINANCE_SYMBOLS[coin]}-{iv}-{ym[0]:04d}-{ym[1]:02d}")
            continue
        out.series.setdefault((coin, iv), []).append(path)
        out.files += [RawFile.of(path), RawFile.of(path.with_name(path.name + ".CHECKSUM"))]
    out.notes = {
        "months": f"{months[0][0]:04d}-{months[0][1]:02d} to {months[-1][0]:04d}-{months[-1][1]:02d}",
        "zips": sum(len(v) for v in out.series.values()),
        "status": status_counts,
        "missing": missing,
        "verified": "every zip's SHA-256 matched its published .CHECKSUM file",
    }
    return out


# --------------------------------------------------------------------------- coinbase


COINBASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
COINBASE_PRODUCTS = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
COINBASE_ORIGIN = date(2015, 7, 20)  # BTC-USD's first daily candle; pages are anchored here for every product
COINBASE_PAGE_DAYS = 300  # the API's maximum candles per request
COINBASE_GRANULARITY = 86_400
COINBASE_MIN_INTERVAL = 0.34  # <= 3 requests per second
COINBASE_SETTLE = timedelta(hours=1)  # a day's candle is only requested an hour after it closed


def last_complete_day(now: datetime) -> date:
    """Open day of the newest daily candle that closed at least ``COINBASE_SETTLE`` before ``now``."""
    return ((now.astimezone(UTC) - COINBASE_SETTLE).date()) - timedelta(days=1)


def coinbase_pages(last_day: date, origin: date = COINBASE_ORIGIN) -> list[tuple[date, date]]:
    """Request windows ``(first open day, last open day)``, both inclusive, of at most 300 days each, on a
    fixed grid from ``origin`` so that complete pages keep their names from one build to the next."""
    pages = []
    start = origin
    while start <= last_day:
        full_end = start + timedelta(days=COINBASE_PAGE_DAYS - 1)
        pages.append((start, min(full_end, last_day)))
        start = full_end + timedelta(days=1)
    return pages


def check_candles(payload: bytes, first: date, last: date) -> list[list[float]]:
    """Parse a candles page and check its shape: rows ``[time, low, high, open, close, volume]`` with every
    ``time`` a whole day inside the requested window. Anything else raises ``ValueError``."""
    rows = json.loads(payload)
    lo = int(datetime(first.year, first.month, first.day, tzinfo=UTC).timestamp())
    hi = int(datetime(last.year, last.month, last.day, tzinfo=UTC).timestamp())
    if not isinstance(rows, list):
        raise ValueError(f"candles page is not a JSON list: {str(rows)[:120]}")
    for row in rows:
        ok = isinstance(row, list) and len(row) == 6 and all(
            isinstance(x, int | float) and not isinstance(x, bool) for x in row
        )
        if not ok or row[0] % COINBASE_GRANULARITY or not lo <= row[0] <= hi:
            raise ValueError(f"unexpected candle row for {first}..{last}: {str(row)[:120]}")
    return rows


def _page_name(product: str, first: date, last: date) -> str:
    return f"{product}_{COINBASE_GRANULARITY}_{first.isoformat()}_{last.isoformat()}.json"


def download_coinbase(
    client: httpx.Client | None,
    raw_dir: Path,
    coins: Sequence[str],
    *,
    now: datetime,
    retry: Retry | None = None,
    limiter: RateLimiter | None = None,
) -> SourceFiles:
    """Daily candles for each coin as raw JSON pages (for the cross-check only).

    A page whose window is complete (300 days, all closed) is kept once fetched; the newest, partial page is
    fetched again and the older partial file replaced. Offline, the pages on disk are used as they are.
    """
    _check_selection(coins, INTERVALS[:1])
    limiter = limiter or RateLimiter(COINBASE_MIN_INTERVAL)
    out = SourceFiles("coinbase")
    pages_total, fetched = 0, 0
    for coin in coins:
        product = COINBASE_PRODUCTS[coin]
        folder = raw_dir / product
        folder.mkdir(parents=True, exist_ok=True)
        if client is None:
            paths = sorted(folder.glob(f"{product}_{COINBASE_GRANULARITY}_*.json"))
            if not paths:
                raise FileNotFoundError(f"offline build: no Coinbase pages for {product} in {folder}")
        else:
            paths = []
            for first, last in coinbase_pages(last_complete_day(now)):
                path = folder / _page_name(product, first, last)
                complete = (last - first).days == COINBASE_PAGE_DAYS - 1
                if not (complete and path.is_file()):
                    got = fetch(
                        client,
                        COINBASE_URL.format(product=product),
                        params={
                            "granularity": str(COINBASE_GRANULARITY),
                            "start": f"{first.isoformat()}T00:00:00Z",
                            "end": f"{last.isoformat()}T00:00:00Z",
                        },
                        max_bytes=1 << 20,
                        retry=retry,
                        limiter=limiter,
                    )
                    check_candles(got.content, first, last)
                    for stale in folder.glob(f"{product}_{COINBASE_GRANULARITY}_{first.isoformat()}_*.json"):
                        stale.unlink()  # an older, shorter version of this page
                    write_atomic(path, got.content)
                    fetched += 1
                paths.append(path)
        for path in paths:
            first, last = (date.fromisoformat(x) for x in path.stem.split("_")[2:4])
            check_candles(path.read_bytes(), first, last)
        pages_total += len(paths)
        out.series[(coin, "1d")] = paths
        out.files += [RawFile.of(p) for p in paths]
    out.notes = {
        "pages": pages_total,
        "fetched_now": fetched,
        "granularity": COINBASE_GRANULARITY,
        "verified": "page shape and that every candle lies in its requested window (the API publishes no "
        "checksums); only candles closed at least an hour before the request are asked for",
    }
    return out
