"""Swap costs on Base, measured read only: 0x indicative prices and a direct Uniswap v3 pool, against the
Coinbase mid (AGENTS.md "Data" and "Costs"; owner approval 2026-11-25).

``python -m lab.data.swap_costs sample`` does three things:

1. **Verifies before any sample.** Each token's code, ``symbol()`` and ``decimals()`` must be the expected ones,
   or the run stops. For the direct route: the Uniswap v3 factory and QuoterV2 must have code; QuoterV2's
   ``factory()`` and ``WETH9()`` must be that factory and WETH; ``getPool`` must return a pool with code for
   every fee tier used; each pool's ``factory()``, ``fee()``, ``token0()`` and ``token1()`` must match; and a
   $100 quote must land within ``SANITY_BPS`` of the Coinbase mid. If any of that fails, the direct route is
   left out and the reason is recorded. Addresses are never guessed.
2. **Samples in rounds.** Each round reads the node's gas price, Base's L1 data fee for a ``DIRECT_TX_BYTES``
   transaction and the ETH mid. Then, for each pair, direction and size, it reads the Coinbase ticker, one 0x
   price, and, pinned to the block 0x quoted at (or the latest block if the node does not have it yet), each
   verified pool's ``slot0`` (the ``REFERENCE_TIER`` pool's is the Base mid) and QuoterV2's quote at each fee
   tier. A value whose request failed is left empty in the table, never read as 0.
3. **Keeps everything.** Every response, failed ones included, goes to ``data/raw/swap_costs/<UTC start>/``
   as it arrives, and ``manifest.json`` holds each file's SHA-256. The table in ``data/swap_costs/`` is built
   from those raw files only (``parse`` rebuilds it after checking the hashes).

**Safety.** The only hosts are ``api.0x.org`` (``GET /swap/permit2/price`` only; never ``/quote``, which returns
a signable transaction, and no taker address), ``mainnet.base.org`` (``POST`` JSON-RPC ``eth_call``,
``eth_gasPrice`` and ``eth_getCode`` only, so nothing here can send a transaction) and Coinbase's ticker for
BTC-USD and ETH-USD. Anything else is refused before any traffic. No request header is ever written, printed
or logged. The 0x key comes from ``ZEROX_API_KEY``; without it the placeholder ``proxy-injected`` is sent and the
session's proxy injects the key.

**Costs**, per sample and route, in bps of the USD value sold at the Coinbase mid (USDC counted at 1 USD):

- ``cost_bps`` = (value sold - value received) / value sold, both at the Coinbase mid: the price cost, all in
  except gas.
- ``fee_bps``: 0x's own fee (``fees.zeroExFee``, valued in its token), or the pool's fee tier on the direct route.
- ``gap_bps``: the Base mid (``slot0`` of the ``REFERENCE_TIER`` pool) against the Coinbase mid, signed so that a
  positive gap costs this trade. ``base_premium_bps`` is the same gap unsigned by direction (positive: Base dearer).
- ``other_bps`` = ``cost_bps`` - ``fee_bps``. ``impact_bps`` = ``other_bps`` - ``gap_bps`` on the 0x route (it holds the
  underlying pools' fees too, which 0x does not report), and ``other_bps`` - ``pool_gap_bps`` on the direct route,
  where ``pool_gap_bps`` is the chosen pool's own mid against Coinbase (``premium_<tier>_bps`` per tier, unsigned).
  The split is additive; the cross terms are under 0.1 bps at these sizes.
- ``gas_usd``: 0x's ``totalNetworkFee``, which includes the L1 data fee. On the direct route it is
  (QuoterV2's ``gasEstimate`` + ``DIRECT_GAS_OVERHEAD``) x the node's ``eth_gasPrice``, plus the L1 data fee
  upper bound for ``DIRECT_TX_BYTES``. Both are valued at the round's ETH mid. ``gas_bps`` is the same over the
  value sold, and ``total_bps`` = ``cost_bps`` + ``gas_bps``.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import httpx
import pandas as pd

from lab.data.sources import RateLimiter, sha256_bytes, write_atomic

# --------------------------------------------------------------------------- what may be asked, and where

ZEROX_HOST = "api.0x.org"
RPC_HOST = "mainnet.base.org"
COINBASE_HOST = "api.exchange.coinbase.com"
ZEROX_PRICE_URL = f"https://{ZEROX_HOST}/swap/permit2/price"
RPC_URL = f"https://{RPC_HOST}/"
TICKER_URL = f"https://{COINBASE_HOST}/products/{{product}}/ticker"
PRODUCTS = ("BTC-USD", "ETH-USD")
ALLOWED = {  # host -> (the one method, the paths)
    ZEROX_HOST: ("GET", frozenset({"/swap/permit2/price"})),
    RPC_HOST: ("POST", frozenset({"/"})),
    COINBASE_HOST: ("GET", frozenset(f"/products/{p}/ticker" for p in PRODUCTS)),
}
RPC_METHODS = frozenset({"eth_call", "eth_gasPrice", "eth_getCode"})
CHAIN_ID = 8453  # Base
USER_AGENT = "strategy-lab/0.1"
MIN_INTERVAL = {ZEROX_HOST: 1.0, RPC_HOST: 0.25, COINBASE_HOST: 0.35}  # seconds between requests per host
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRIES = 2
TIMEOUT = httpx.Timeout(30.0, connect=15.0)
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class Token:
    """A token on Base. ``product`` is the Coinbase product that prices it in USD (None: USDC, at 1 USD)."""

    symbol: str
    address: str
    decimals: int
    product: str | None


TOKENS = {
    t.symbol: t
    for t in (
        Token("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, None),
        Token("WETH", "0x4200000000000000000000000000000000000006", 18, "ETH-USD"),
        Token("cbBTC", "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8, "BTC-USD"),
    )
}
USDC = TOKENS["USDC"]
BY_ADDRESS = {t.address.lower(): t for t in TOKENS.values()}
COINS = ("WETH", "cbBTC")
PAIRS = (("USDC", "WETH"), ("WETH", "USDC"), ("USDC", "cbBTC"), ("cbBTC", "USDC"))
SIZES_USD = (100, 1_000, 10_000, 50_000)

UNISWAP_V3_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000F"  # the OP-stack predeploy on Base
FEE_TIERS = (100, 500, 3000)  # hundredths of a bp: 1, 5 and 30 bps
REFERENCE_TIER = 500  # the Base mid comes from this pool: deep in both pairs, its mid within ~5 bps of the market
SANITY_BPS = 200.0  # a verification quote further than this from the Coinbase mid disables the direct route
# Gas a direct swap needs beyond QuoterV2's gasEstimate (the pool swap and the output transfer): 21,000 for
# the transaction itself plus 60,000 allowed for the router, the input transfer and calldata. A stated
# allowance, not a measurement.
DIRECT_GAS_OVERHEAD = 81_000
DIRECT_TX_BYTES = 400  # the unsigned transaction size the direct route's L1 data fee upper bound is read for

SELECTORS = {  # first 4 bytes of keccak-256 of the signature (tests recompute each one)
    "symbol()": "95d89b41",
    "decimals()": "313ce567",
    "factory()": "c45a0155",
    "WETH9()": "4aa4a4fc",
    "token0()": "0dfe1681",
    "token1()": "d21220a7",
    "fee()": "ddca3f43",
    "slot0()": "3850c7bd",
    "getPool(address,address,uint24)": "1698ee82",
    "quoteExactInputSingle((address,address,uint256,uint24,uint160))": "c6a5026a",
    "getL1FeeUpperBound(uint256)": "f1c7a58b",
}

# 0x source names of established exchanges. Anything else is listed in ``unknown_sources`` for vetting. The match
# is by 0x's name only: a price response does not say which contract a source is.
WELL_KNOWN_SOURCES = frozenset(
    {
        "Uniswap_V2",
        "Uniswap_V3",
        "Uniswap_V4",
        "Aerodrome_V2",
        "Aerodrome_V3",
        "Aero_Slipstream",
        "Curve",
        "Balancer_V2",
        "Balancer_V3",
        "PancakeSwap_V3",
        "SushiSwap",
        "SushiSwap_V3",
        "Maverick_V2",
    }
)


class DisallowedRequestError(ValueError):
    """A request this module must never send (host, path, method or RPC method off the list)."""


class ParseError(ValueError):
    """A response that failed, or that does not have the expected shape."""


class VerificationError(RuntimeError):
    """An on-chain check did not hold."""


class ChecksumError(ValueError):
    """A raw file does not match the SHA-256 in its manifest."""


# --------------------------------------------------------------------------- requests


def check_request(method: str, url: str | httpx.URL) -> httpx.URL:
    """Return ``url`` parsed, or raise :class:`DisallowedRequestError` unless it is https on an allowed host,
    with that host's one method and one of its paths."""
    parsed = httpx.URL(str(url))
    if parsed.scheme != "https" or parsed.userinfo or parsed.port not in (None, 443):
        raise DisallowedRequestError(f"only plain https URLs are allowed: {parsed.host}")
    if parsed.host not in ALLOWED:
        raise DisallowedRequestError(f"host not allowed: {parsed.host}")
    allowed_method, paths = ALLOWED[parsed.host]
    if method != allowed_method or parsed.path not in paths:
        raise DisallowedRequestError(f"not allowed on {parsed.host}: {method} {parsed.path}")
    return parsed


@dataclass(frozen=True)
class Exchange:
    """One request's outcome: its sequence number in the raw folder, status, body and transport error."""

    seq: int
    status: int | None
    body: bytes | None
    error: str | None


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class RawRecorder:
    """Writes each exchange to ``<raw_dir>/<seq>-<kind>.json`` as it happens, and the manifest of SHA-256s.

    It is never given a request header. ``secrets`` (the 0x key, if one is configured) are replaced by
    ``<redacted>`` in any error text or body before anything is written, and the file says so."""

    def __init__(self, raw_dir: Path, secrets: Iterable[str] = ()) -> None:
        self.dir = raw_dir
        self.seq = 0
        self.secrets = [s for s in secrets if s]

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "<redacted>")
        return text

    def record(
        self,
        kind: str,
        request: dict,
        status: int | None,
        content: bytes | None,
        error: str | None,
        ts: datetime,
        elapsed: float,
        attempt: int,
    ) -> int:
        self.seq += 1
        envelope = {
            "seq": self.seq,
            "kind": kind,
            "request": request,
            "attempt": attempt,
            "ts_utc": iso(ts),
            "elapsed_s": round(elapsed, 6),
            "status": status,
            "error": None if error is None else self.scrub(error),
            "body": None,
            "body_sha256": None,
            "scrubbed": False,
        }
        if content is not None:
            envelope["body_sha256"] = sha256_bytes(content)
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                envelope["body_b64"] = base64.b64encode(content).decode("ascii")
            else:
                envelope["body"] = self.scrub(text)
                envelope["scrubbed"] = envelope["body"] != text
        envelope["scrubbed"] = envelope["scrubbed"] or (error is not None and envelope["error"] != error)
        write_atomic(self.dir / f"{self.seq:05d}-{kind}.json", _dumps(envelope))
        return self.seq

    def write_json(self, name: str, obj: object) -> None:
        write_atomic(self.dir / name, _dumps(obj))

    def append_jsonl(self, name: str, rows: Sequence[dict]) -> None:
        path = self.dir / name
        old = path.read_bytes() if path.exists() else b""
        new = b"".join(json.dumps(r, sort_keys=True).encode() + b"\n" for r in rows)
        write_atomic(path, old + new)

    def write_manifest(self, info: dict) -> None:
        files = {
            p.name: sha256_bytes(p.read_bytes())
            for p in sorted(self.dir.iterdir())
            if p.is_file() and p.name != "manifest.json" and not p.name.endswith(".tmp")
        }
        self.write_json("manifest.json", {**info, "files": files})


def _dumps(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, indent=1).encode() + b"\n"


class Probe:
    """The one request path: allow-list check, per-host pacing, retries of 429, 5xx and transport errors
    (each attempt recorded), and nothing but the listed requests."""

    def __init__(
        self,
        client: httpx.Client,
        recorder: RawRecorder,
        *,
        api_key: str,
        retries: int = RETRIES,
        min_interval: dict[str, float] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client, self.recorder, self.api_key, self.retries = client, recorder, api_key, retries
        self.sleep, self.clock, self.now = sleep, clock, now
        intervals = MIN_INTERVAL if min_interval is None else min_interval
        self.limiters = {h: RateLimiter(s, clock=clock, sleep=sleep) for h, s in intervals.items()}

    def exchange(
        self,
        kind: str,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> Exchange:
        parsed = check_request(method, url)
        request = {"method": method, "url": str(parsed), "params": params, "json": body}
        attempt = 0
        while True:
            self.limiters[parsed.host].wait()
            ts, t0 = self.now(), self.clock()
            status = content = error = None
            try:
                r = self.client.request(
                    method, parsed, params=params, json=body, headers=headers, follow_redirects=False
                )
                status, content = r.status_code, r.content
            except httpx.RequestError as exc:
                error = f"{type(exc).__name__}: {exc}"
            seq = self.recorder.record(kind, request, status, content, error, ts, self.clock() - t0, attempt)
            if (error is None and status not in RETRY_STATUSES) or attempt == self.retries:
                return Exchange(seq, status, content, None if error is None else self.recorder.scrub(error))
            self.sleep(2.0**attempt)
            attempt += 1

    def ticker(self, product: str) -> Exchange:
        return self.exchange("ticker", "GET", TICKER_URL.format(product=product))

    def zerox_price(self, sell: Token, buy: Token, amount: int) -> Exchange:
        params = {
            "chainId": str(CHAIN_ID),
            "sellToken": sell.address,
            "buyToken": buy.address,
            "sellAmount": str(amount),
        }
        headers = {"0x-api-key": self.api_key, "0x-version": "v2"}
        return self.exchange("zerox_price", "GET", ZEROX_PRICE_URL, params=params, headers=headers)

    def rpc(self, kind: str, method: str, params: list) -> Exchange:
        if method not in RPC_METHODS:
            raise DisallowedRequestError(f"RPC method not allowed: {method}")
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return self.exchange(kind, "POST", RPC_URL, body=body)

    def call(self, kind: str, to: str, data: str, tag: str = "latest") -> Exchange:
        return self.rpc(kind, "eth_call", [{"to": to, "data": data}, tag])


# --------------------------------------------------------------------------- parsing


def json_of(ex: Exchange) -> object:
    """The JSON body of a successful exchange; :class:`ParseError` with the reason otherwise."""
    if ex.error is not None:
        raise ParseError(ex.error)
    text = (ex.body or b"").decode("utf-8", errors="replace")
    if ex.status != 200:
        raise ParseError(f"HTTP {ex.status}: {text[:300]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"not JSON: {text[:120]}") from exc


def rpc_result(ex: Exchange) -> str:
    """The ``result`` hex string of a JSON-RPC answer; :class:`ParseError` for an RPC error or another shape."""
    obj = json_of(ex)
    if not isinstance(obj, dict):
        raise ParseError(f"not a JSON-RPC answer: {str(obj)[:120]}")
    if obj.get("error") is not None:
        err = obj["error"]
        raise ParseError(f"RPC error {err.get('code')}: {err.get('message')}" if isinstance(err, dict) else str(err))
    result = obj.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ParseError(f"not a hex result: {str(result)[:120]}")
    return result


def word_address(address: str) -> str:
    a = address.lower().removeprefix("0x")
    if len(a) != 40 or not _is_hex(a):
        raise ValueError(f"not an address: {address}")
    return a.rjust(64, "0")


def word_uint(n: int) -> str:
    if not 0 <= n < 2**256:
        raise ValueError(f"not a uint256: {n}")
    return f"{n:064x}"


def calldata(signature: str, *words: str) -> str:
    return "0x" + SELECTORS[signature] + "".join(words)


def quote_calldata(sell: Token, buy: Token, amount: int, tier: int) -> str:
    """QuoterV2 ``quoteExactInputSingle((tokenIn, tokenOut, amountIn, fee, sqrtPriceLimitX96 = 0))``."""
    return calldata(
        "quoteExactInputSingle((address,address,uint256,uint24,uint160))",
        word_address(sell.address),
        word_address(buy.address),
        word_uint(amount),
        word_uint(tier),
        word_uint(0),
    )


def _is_hex(text: str) -> bool:
    return all(c in "0123456789abcdefABCDEF" for c in text)


def words(result: str, n: int) -> list[int]:
    """The first ``n`` 32-byte words of an ``eth_call`` result as integers."""
    h = result.removeprefix("0x")
    if len(h) < 64 * n or not _is_hex(h):
        raise ParseError(f"expected {n} words, got {result[:80]!r}")
    return [int(h[64 * i : 64 * (i + 1)], 16) for i in range(n)]


def quantity(result: str) -> int:
    """A JSON-RPC quantity such as ``eth_gasPrice``'s: hex digits without padding."""
    h = result.removeprefix("0x")
    if not h or len(h) > 64 or not _is_hex(h):
        raise ParseError(f"not a quantity: {result[:80]!r}")
    return int(h, 16)


def as_address(word: int) -> str:
    if word >= 2**160:
        raise ParseError(f"not an address word: {word:#x}")
    return f"0x{word:040x}"


def decode_string(result: str) -> str:
    """An ABI-encoded ``string`` return value."""
    (offset,) = words(result, 1)
    h = result.removeprefix("0x")
    start = 2 * offset
    if offset % 32 or len(h) < start + 64:
        raise ParseError(f"bad string offset in {result[:80]!r}")
    length = int(h[start : start + 64], 16)
    data = h[start + 64 : start + 64 + 2 * length]
    if len(data) != 2 * length:
        raise ParseError(f"string shorter than its length in {result[:80]!r}")
    try:
        return bytes.fromhex(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(f"string not UTF-8 in {result[:80]!r}") from exc


@dataclass(frozen=True)
class Ticker:
    bid: float
    ask: float
    time: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def parse_ticker(obj: object) -> Ticker:
    try:
        bid, ask, ts = float(obj["bid"]), float(obj["ask"]), str(obj["time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"malformed ticker: {str(obj)[:120]}") from exc
    if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
        raise ParseError(f"bad bid/ask: {bid} / {ask}")
    return Ticker(bid, ask, ts)


@dataclass(frozen=True)
class ZeroXPrice:
    buy_amount: int
    fee_amount: int  # 0x's own fee, in ``fee_token`` units (0 when no fee is reported)
    fee_token: str | None  # lower-case address
    gas: int
    gas_price: int
    total_network_fee: int  # wei, L1 data fee included
    block: int
    fills: tuple[tuple[str, int], ...]  # (source, proportionBps) per fill


def parse_zerox(obj: object, sell: Token, buy: Token, sell_amount: int) -> ZeroXPrice:
    """A 0x ``/swap/permit2/price`` answer for exactly this request, or :class:`ParseError`."""
    if not isinstance(obj, dict) or obj.get("liquidityAvailable") is not True:
        raise ParseError(f"no liquidity available: {str(obj)[:200]}")
    try:
        asked = (obj["sellToken"].lower(), obj["buyToken"].lower(), int(obj["sellAmount"]))
        fee = (obj.get("fees") or {}).get("zeroExFee")
        price = ZeroXPrice(
            buy_amount=int(obj["buyAmount"]),
            fee_amount=int(fee["amount"]) if fee else 0,
            fee_token=fee["token"].lower() if fee else None,
            gas=int(obj["gas"]),
            gas_price=int(obj["gasPrice"]),
            total_network_fee=int(obj["totalNetworkFee"]),
            block=int(obj["blockNumber"]),
            fills=tuple((str(f["source"]), int(f["proportionBps"])) for f in obj["route"]["fills"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ParseError(f"malformed price: {type(exc).__name__} {exc}") from exc
    if asked != (sell.address.lower(), buy.address.lower(), sell_amount):
        raise ParseError(f"the answer is for another request: {asked}")
    return price


@dataclass(frozen=True)
class DirectQuote:
    tier: int
    amount_out: int
    ticks_crossed: int
    gas_estimate: int


def parse_quote(result: str, tier: int) -> DirectQuote:
    """QuoterV2's ``(amountOut, sqrtPriceX96After, initializedTicksCrossed, gasEstimate)``."""
    amount_out, _, ticks, gas = words(result, 4)
    if amount_out == 0:
        raise ParseError(f"fee {tier}: zero output")
    return DirectQuote(tier, amount_out, ticks, gas)


def ordered(a: Token, b: Token) -> tuple[Token, Token]:
    """A Uniswap pool's (token0, token1): the lower address first."""
    return (a, b) if int(a.address, 16) < int(b.address, 16) else (b, a)


def pool_price_usd(sqrt_price_x96: int, coin: Token) -> float:
    """USD per ``coin`` from the ``slot0`` price of a (coin, USDC) pool, USDC counted at 1 USD.

    ``(sqrtPriceX96 / 2**96)**2`` is token1 per token0 in base units; times ``10**(dec0 - dec1)`` in whole tokens."""
    if sqrt_price_x96 <= 0:
        raise ParseError("zero pool price")
    token0, token1 = ordered(coin, USDC)
    p = Fraction(sqrt_price_x96**2, 2**192) * Fraction(10) ** (token0.decimals - token1.decimals)
    return float(p) if token0 is coin else float(1 / p)


# --------------------------------------------------------------------------- cost maths


def sell_amount_units(sell: Token, size_usd: float, coin_mid: float) -> int:
    """Base units of ``sell`` worth ``size_usd`` at the Coinbase mid (USDC at 1 USD), rounded down."""
    usd_per_token = Fraction(1) if sell.product is None else Fraction(coin_mid)
    return math.floor(Fraction(size_usd) / usd_per_token * 10**sell.decimals)


def token_usd(token: Token, units: int, coin_mid: float) -> float:
    return units / 10**token.decimals * (1.0 if token.product is None else coin_mid)


def cost_bps(value_in: float, value_out: float) -> float:
    return (value_in - value_out) / value_in * 1e4


def premium_bps(base_mid: float, coinbase_mid: float) -> float:
    """How much dearer the coin is on Base than on Coinbase, in bps (negative: cheaper)."""
    return (base_mid / coinbase_mid - 1) * 1e4


# --------------------------------------------------------------------------- verification


def has_code(probe: Probe, address: str) -> bool:
    return rpc_result(probe.rpc("get_code", "eth_getCode", [address, "latest"])) not in ("0x", "0x0")


def read_word(probe: Probe, kind: str, to: str, signature: str, *args: str) -> int:
    return words(rpc_result(probe.call(kind, to, calldata(signature, *args))), 1)[0]


def verify_tokens(probe: Probe) -> None:
    """Each token has code and the expected ``symbol()`` and ``decimals()``; :class:`VerificationError`
    otherwise (a failed request too: an unverified token is never used)."""
    for t in TOKENS.values():
        try:
            if not has_code(probe, t.address):
                raise VerificationError(f"{t.symbol}: no contract code at {t.address}")
            symbol = decode_string(rpc_result(probe.call("token_symbol", t.address, calldata("symbol()"))))
            decimals = read_word(probe, "token_decimals", t.address, "decimals()")
        except ParseError as exc:
            raise VerificationError(f"{t.symbol}: could not read the token ({exc})") from exc
        if (symbol, decimals) != (t.symbol, t.decimals):
            raise VerificationError(
                f"{t.address}: symbol {symbol!r} and decimals {decimals}, expected {t.symbol!r} and {t.decimals}"
            )


@dataclass
class DirectRoute:
    """The verified Uniswap v3 pools (coin -> fee tier -> address), or why the direct route is left out."""

    enabled: bool
    reason: str | None = None
    pools: dict[str, dict[str, str]] = field(default_factory=dict)
    checks: dict[str, float] = field(default_factory=dict)  # coin -> the $100 sanity quote's cost in bps


def _verify_pool(probe: Probe, coin: Token, tier: int) -> str:
    token0, token1 = ordered(coin, USDC)
    pool = as_address(
        read_word(
            probe,
            "get_pool",
            UNISWAP_V3_FACTORY,
            "getPool(address,address,uint24)",
            word_address(token0.address),
            word_address(token1.address),
            word_uint(tier),
        )
    )
    if int(pool, 16) == 0 or not has_code(probe, pool):
        raise VerificationError(f"no {coin.symbol}/USDC pool with code at fee {tier} (getPool: {pool})")
    expected = {
        "factory()": int(UNISWAP_V3_FACTORY, 16),
        "fee()": tier,
        "token0()": int(token0.address, 16),
        "token1()": int(token1.address, 16),
    }
    for signature, value in expected.items():
        got = read_word(probe, "pool_check", pool, signature)
        if got != value:
            raise VerificationError(f"pool {pool}: {signature} is {got:#x}, expected {value:#x}")
    return pool


def verify_direct(probe: Probe, mids: dict[str, float]) -> DirectRoute:
    """Check the Uniswap v3 contracts and pools (module docstring, step 1). Never raises for a failed check:
    the direct route is then left out, with the reason."""
    try:
        for address, name in ((UNISWAP_V3_FACTORY, "factory"), (QUOTER_V2, "QuoterV2")):
            if not has_code(probe, address):
                raise VerificationError(f"{name}: no contract code at {address}")
        for signature, expected in (("factory()", UNISWAP_V3_FACTORY), ("WETH9()", TOKENS["WETH"].address)):
            got = as_address(read_word(probe, "quoter_check", QUOTER_V2, signature))
            if got != expected.lower():
                raise VerificationError(f"QuoterV2 {signature} is {got}, expected {expected.lower()}")
        route = DirectRoute(True)
        for symbol in COINS:
            coin = TOKENS[symbol]
            route.pools[symbol] = {str(tier): _verify_pool(probe, coin, tier) for tier in FEE_TIERS}
            if coin.product not in mids:
                raise VerificationError(f"no Coinbase mid for {coin.product}: cannot check a quote")
            amount = sell_amount_units(USDC, 100, 1.0)
            outs = []
            for tier in FEE_TIERS:
                try:
                    outs.append(parse_quote(rpc_result(probe.call("quote_check", QUOTER_V2, quote_calldata(USDC, coin, amount, tier))), tier).amount_out)
                except ParseError:
                    continue
            if not outs:
                raise VerificationError(f"QuoterV2 gave no $100 USDC->{symbol} quote")
            check = cost_bps(100.0, token_usd(coin, max(outs), mids[coin.product]))
            route.checks[symbol] = check
            if abs(check) > SANITY_BPS:
                raise VerificationError(
                    f"QuoterV2's $100 USDC->{symbol} quote is {check:.1f} bps from the Coinbase mid (limit {SANITY_BPS})"
                )
        return route
    except (VerificationError, ParseError) as exc:
        return DirectRoute(False, str(exc))


# --------------------------------------------------------------------------- sampling


def _failed(ex: Exchange) -> bool:
    try:
        rpc_result(ex)
    except ParseError:
        return True
    return False


def take_sample(probe: Probe, rnd: int, idx: int, sell: Token, buy: Token, size: int, direct: DirectRoute) -> dict:
    """Ask 0x and the direct pool for one trade at the same moment; returns the sample's record (sequence
    numbers of its exchanges). A failed ticker ends the sample: nothing is priced without a mid."""
    coin = buy if sell.product is None else sell
    rec = {
        "round": rnd,
        "sample": idx,
        "ts_utc": iso(probe.now()),
        "sell": sell.symbol,
        "buy": buy.symbol,
        "size_usd": size,
        "ticker": None,
        "sell_amount": None,
        "zerox": None,
        "tag": None,
        "slot0": None,
        "quotes": {},
    }
    tk = probe.ticker(coin.product)
    rec["ticker"] = tk.seq
    try:
        mid = parse_ticker(json_of(tk)).mid
    except ParseError:
        return rec
    amount = sell_amount_units(sell, size, mid)
    rec["sell_amount"] = str(amount)
    zx = probe.zerox_price(sell, buy, amount)
    rec["zerox"] = zx.seq
    if not direct.enabled:
        return rec
    try:
        tag = hex(parse_zerox(json_of(zx), sell, buy, amount).block)
    except ParseError:
        tag = "latest"
    pools = direct.pools[coin.symbol]
    s0 = probe.call("slot0", pools[str(REFERENCE_TIER)], calldata("slot0()"), tag)
    if tag != "latest" and _failed(s0):  # the node may not have 0x's block yet
        tag = "latest"
        s0 = probe.call("slot0", pools[str(REFERENCE_TIER)], calldata("slot0()"), tag)
    rec["tag"], rec["slot0"] = tag, {str(REFERENCE_TIER): s0.seq}
    for tier in FEE_TIERS:
        if tier != REFERENCE_TIER:
            rec["slot0"][str(tier)] = probe.call("slot0", pools[str(tier)], calldata("slot0()"), tag).seq
        rec["quotes"][str(tier)] = probe.call("quote", QUOTER_V2, quote_calldata(sell, buy, amount, tier), tag).seq
    return rec


def run_round(probe: Probe, rnd: int, direct: DirectRoute, sizes: Sequence[int]) -> tuple[dict, list[dict]]:
    start = iso(probe.now())
    gas = probe.rpc("gas_price", "eth_gasPrice", [])
    l1 = probe.call("l1_fee", GAS_PRICE_ORACLE, calldata("getL1FeeUpperBound(uint256)", word_uint(DIRECT_TX_BYTES)))
    eth = probe.ticker("ETH-USD")
    record = {"round": rnd, "ts_utc": start, "gas_price": gas.seq, "l1_fee": l1.seq, "eth_ticker": eth.seq}
    samples: list[dict] = []
    for sell, buy in PAIRS:
        for size in sizes:
            samples.append(take_sample(probe, rnd, len(samples), TOKENS[sell], TOKENS[buy], size, direct))
    return record, samples


# --------------------------------------------------------------------------- the table, from raw files only

COLUMNS = (
    "run", "round", "sample", "ts_utc", "pair", "sell", "buy", "coin", "size_usd", "route", "ok", "error",
    "cb_bid", "cb_ask", "cb_mid", "eth_mid", "sell_amount", "buy_amount", "value_in_usd", "value_out_usd",
    "cost_bps", "fee_bps", "fee_tier", "fee_token", "other_bps", "base_mid_usd", "base_premium_bps", "gap_bps",
    "pool_gap_bps", "impact_bps", *(f"premium_{t}_bps" for t in FEE_TIERS), "gas_units", "gas_price_wei", "l1_fee_wei", "gas_usd", "gas_bps", "total_bps", "block",
    "ticks_crossed", "sources", "unknown_sources",
)  # fmt: skip
ROUTES = ("0x", "uniswap_v3")


def _maybe(fn: Callable[[], object]) -> object:
    try:
        return fn()
    except ParseError:
        return None


def round_context(rec: dict, ex: Callable[[int], Exchange]) -> dict:
    """The round's ETH mid, node gas price and L1 fee upper bound (None where the request failed)."""
    return {
        "eth_mid": _maybe(lambda: parse_ticker(json_of(ex(rec["eth_ticker"]))).mid),
        "gas_price": _maybe(lambda: quantity(rpc_result(ex(rec["gas_price"])))),
        "l1_fee": _maybe(lambda: words(rpc_result(ex(rec["l1_fee"])), 1)[0]),
    }


def _gas(row: dict, gas_wei: int | None, eth_mid: float | None) -> None:
    if gas_wei is not None and eth_mid is not None:
        row["gas_usd"] = gas_wei / 1e18 * eth_mid
        row["gas_bps"] = row["gas_usd"] / row["value_in_usd"] * 1e4
        row["total_bps"] = row["cost_bps"] + row["gas_bps"]


def _priced(common: dict, buy: Token, buy_units: int, coin_mid: float) -> dict:
    row = {**common, "ok": True, "buy_amount": buy_units / 10**buy.decimals}
    row["value_out_usd"] = token_usd(buy, buy_units, coin_mid)
    row["cost_bps"] = cost_bps(row["value_in_usd"], row["value_out_usd"])
    return row


def _split(row: dict, gap: float | None) -> dict:
    """``other_bps`` = cost - fee, and ``impact_bps`` = other - ``gap`` when the gap is known."""
    row["other_bps"] = row["cost_bps"] - row["fee_bps"]
    if gap is not None:
        row["impact_bps"] = row["other_bps"] - gap
    return row


def zerox_row(common: dict, ex: Exchange, sell: Token, buy: Token, amount: int, coin_mid: float, ctx: dict) -> dict:
    try:
        p = parse_zerox(json_of(ex), sell, buy, amount)
        fee_token = None if p.fee_token is None else BY_ADDRESS.get(p.fee_token)
        if p.fee_token is not None and fee_token not in (sell, buy):
            raise ParseError(f"0x fee in an unexpected token {p.fee_token}")
    except ParseError as exc:
        return {**common, "route": "0x", "ok": False, "error": f"0x: {exc}"}
    row = _priced({**common, "route": "0x"}, buy, p.buy_amount, coin_mid)
    fee_usd = 0.0 if fee_token is None else token_usd(fee_token, p.fee_amount, coin_mid)
    row["fee_bps"] = fee_usd / row["value_in_usd"] * 1e4
    row["fee_token"] = None if fee_token is None else fee_token.symbol
    row["gas_units"], row["gas_price_wei"] = p.gas, p.gas_price
    row["l1_fee_wei"] = p.total_network_fee - p.gas * p.gas_price
    row["block"] = str(p.block)
    row["sources"] = ";".join(f"{s}:{bps}" for s, bps in p.fills)
    row["unknown_sources"] = ";".join(sorted({s for s, _ in p.fills} - WELL_KNOWN_SOURCES))
    _gas(row, p.total_network_fee, ctx["eth_mid"])
    return _split(row, row["gap_bps"])


def direct_row(common: dict, rec: dict, ex: Callable[[int], Exchange], buy: Token, coin_mid: float, ctx: dict) -> dict:
    quotes, errors = [], []
    for tier, seq in rec["quotes"].items():
        try:
            quotes.append(parse_quote(rpc_result(ex(seq)), int(tier)))
        except ParseError as exc:
            errors.append(f"fee {tier}: {exc}")
    if not quotes:
        return {**common, "route": "uniswap_v3", "ok": False, "error": "uniswap_v3: " + ("; ".join(errors) or "no quote")}
    best = max(quotes, key=lambda q: q.amount_out)
    row = _priced({**common, "route": "uniswap_v3"}, buy, best.amount_out, coin_mid)
    row["fee_tier"], row["fee_bps"], row["ticks_crossed"] = best.tier, best.tier / 100, best.ticks_crossed
    row["gas_units"] = best.gas_estimate + DIRECT_GAS_OVERHEAD
    row["gas_price_wei"], row["l1_fee_wei"] = ctx["gas_price"], ctx["l1_fee"]
    row["block"] = str(int(rec["tag"], 16)) if rec["tag"] != "latest" else "latest"
    gas_wei = None if None in (ctx["gas_price"], ctx["l1_fee"]) else row["gas_units"] * ctx["gas_price"] + ctx["l1_fee"]
    _gas(row, gas_wei, ctx["eth_mid"])
    premium = row[f"premium_{best.tier}_bps"]  # the chosen pool's own mid: what is left is that pool's impact
    if premium is not None:
        row["pool_gap_bps"] = premium if row["coin"] == row["buy"] else -premium
    return _split(row, row["pool_gap_bps"])


def sample_rows(rec: dict, ctx: dict, direct: DirectRoute, ex: Callable[[int], Exchange], run: str) -> list[dict]:
    """One row per route for one sample, computed from its recorded exchanges."""
    sell, buy = TOKENS[rec["sell"]], TOKENS[rec["buy"]]
    coin = buy if sell.product is None else sell
    common = dict.fromkeys(COLUMNS)
    common.update(
        run=run, round=rec["round"], sample=rec["sample"], ts_utc=rec["ts_utc"], pair=f"{sell.symbol}->{buy.symbol}",
        sell=sell.symbol, buy=buy.symbol, coin=coin.symbol, size_usd=rec["size_usd"], eth_mid=ctx["eth_mid"],
    )  # fmt: skip
    routes = ROUTES if direct.enabled else ROUTES[:1]
    try:
        tk = parse_ticker(json_of(ex(rec["ticker"])))
    except ParseError as exc:
        return [{**common, "route": r, "ok": False, "error": f"coinbase ticker: {exc}"} for r in routes]
    amount = int(rec["sell_amount"])
    common.update(cb_bid=tk.bid, cb_ask=tk.ask, cb_mid=tk.mid, sell_amount=amount / 10**sell.decimals)
    common["value_in_usd"] = token_usd(sell, amount, tk.mid)
    for tier, seq in (rec["slot0"] or {}).items():
        mid = _maybe(lambda s=seq: pool_price_usd(words(rpc_result(ex(s)), 1)[0], coin))
        if mid is not None:
            common[f"premium_{tier}_bps"] = premium_bps(mid, tk.mid)
            if int(tier) == REFERENCE_TIER:
                common["base_mid_usd"] = mid
                common["base_premium_bps"] = common[f"premium_{tier}_bps"]
                common["gap_bps"] = common["base_premium_bps"] * (1 if coin is buy else -1)
    rows = [zerox_row(common, ex(rec["zerox"]), sell, buy, amount, tk.mid, ctx)]
    if direct.enabled:
        rows.append(direct_row(common, rec, ex, buy, tk.mid, ctx))
    return rows


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def check_manifest(raw_dir: Path) -> dict:
    """The manifest, after checking every file it lists against its SHA-256 (:class:`ChecksumError` otherwise)."""
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        path = raw_dir / name
        if not path.is_file() or sha256_bytes(path.read_bytes()) != digest:
            raise ChecksumError(f"{path}: missing or changed since the manifest was written")
    return manifest


def load_exchange(path: Path) -> Exchange:
    env = json.loads(path.read_text())
    if env.get("body") is not None:
        body = env["body"].encode("utf-8")
    elif env.get("body_b64") is not None:
        body = base64.b64decode(env["body_b64"])
    else:
        body = None
    return Exchange(env["seq"], env["status"], body, env["error"])


def build_table(raw_dir: Path) -> pd.DataFrame:
    """The cost table of one run, from its raw files only (each checked against the manifest first)."""
    manifest = check_manifest(raw_dir)
    listed = {name for name in manifest["files"] if name[:5].isdigit()}
    exchanges = {int(n[:5]): load_exchange(raw_dir / n) for n in listed}
    verification = json.loads((raw_dir / "verification.json").read_text())
    direct = DirectRoute(**(verification["direct"] or {"enabled": False, "reason": verification["tokens"]}))
    rounds = {r["round"]: round_context(r, exchanges.__getitem__) for r in read_jsonl(raw_dir / "rounds.jsonl")}
    rows = []
    for rec in read_jsonl(raw_dir / "samples.jsonl"):
        rows += sample_rows(rec, rounds[rec["round"]], direct, exchanges.__getitem__, raw_dir.name)
    return pd.DataFrame(rows, columns=list(COLUMNS))


def write_table(table: pd.DataFrame, raw_dir: Path, out_dir: Path) -> Path:
    """``<out_dir>/<run>.parquet`` and ``.csv``, plus ``.json`` naming the raw folder and its manifest hash."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / raw_dir.name
    table.to_parquet(stem.with_name(stem.name + ".parquet"), index=False)
    table.to_csv(stem.with_name(stem.name + ".csv"), index=False)
    meta = {
        "raw_dir": str(raw_dir),
        "manifest_sha256": sha256_bytes((raw_dir / "manifest.json").read_bytes()),
        "parser_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "rows": len(table),
        "rows_ok": int(table["ok"].sum()),
    }
    write_atomic(stem.with_name(stem.name + ".json"), _dumps(meta))
    return stem.with_name(stem.name + ".parquet")


# --------------------------------------------------------------------------- summaries


def _p90(values: pd.Series) -> float:
    return values.quantile(0.9)


def summarize(table: pd.DataFrame) -> pd.DataFrame:
    """Per pair, size and route: samples, failures, the median, 90th percentile (linear interpolation) and worst
    of the price cost and the total, the median fee and split, and the gas in USD."""
    keys = ["pair", "size_usd", "route"]
    counts = table.groupby(keys).agg(n=("ok", "size"), failed=("ok", lambda s: int((~s.astype(bool)).sum())))
    ok = table[table["ok"].astype(bool)]
    stats = ok.groupby(keys).agg(
        cost_med=("cost_bps", "median"),
        cost_p90=("cost_bps", _p90),
        cost_worst=("cost_bps", "max"),
        total_med=("total_bps", "median"),
        total_p90=("total_bps", _p90),
        total_worst=("total_bps", "max"),
        fee_med=("fee_bps", "median"),
        other_med=("other_bps", "median"),
        other_p90=("other_bps", _p90),
        gap_med=("gap_bps", "median"),
        gas_usd_med=("gas_usd", "median"),
        gas_usd_p90=("gas_usd", _p90),
        gas_usd_worst=("gas_usd", "max"),
    )
    out = counts.join(stats).reset_index()
    order = {f"{s}->{b}": i for i, (s, b) in enumerate(PAIRS)}
    out = out.sort_values(keys, key=lambda c: c.map(order) if c.name == "pair" else c, kind="stable")
    return out.reset_index(drop=True)


def gap_summary(table: pd.DataFrame) -> pd.DataFrame:
    """The Base mid against the Coinbase mid per coin, one value per sample (positive: Base dearer)."""
    one = table.drop_duplicates(["run", "round", "sample"]).dropna(subset=["base_premium_bps"])
    return (
        one.groupby("coin")["base_premium_bps"]
        .agg(n="size", median="median", min="min", max="max")
        .reset_index()
    )


def source_summary(table: pd.DataFrame) -> pd.DataFrame:
    """Each 0x source not on ``WELL_KNOWN_SOURCES``: in how many priced samples it appeared, per pair."""
    zx = table[(table["route"] == "0x") & table["ok"].astype(bool)]
    rows = [
        {"source": s, "pair": pair}
        for pair, names in zip(zx["pair"], zx["unknown_sources"], strict=True)
        for s in (names or "").split(";")
        if s
    ]
    if not rows:
        return pd.DataFrame(columns=["source", "pair", "samples"])
    return pd.DataFrame(rows).groupby(["source", "pair"]).size().rename("samples").reset_index()


# --------------------------------------------------------------------------- the run


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, transport=transport, follow_redirects=False
    )


def sample(
    data_dir: Path,
    rounds: int,
    interval_s: float,
    sizes: Sequence[int] = SIZES_USD,
    *,
    client: httpx.Client | None = None,
    api_key: str = "proxy-injected",
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    out: Callable[[str], None] = print,
) -> Path:
    """Verify, then take ``rounds`` rounds ``interval_s`` apart (start to start); returns the raw folder.

    Raises :class:`VerificationError` (after recording it) when a token does not verify."""
    if rounds < 1 or interval_s < 0 or not sizes or min(sizes) <= 0:
        raise ValueError("rounds >= 1, interval >= 0 and positive sizes are required")
    started = now()
    raw_dir = data_dir / "raw" / "swap_costs" / started.strftime("%Y%m%dT%H%M%SZ")
    raw_dir.mkdir(parents=True, exist_ok=False)  # a run never writes into another run's folder
    recorder = RawRecorder(raw_dir, secrets=[api_key])
    probe = Probe(client or make_client(), recorder, api_key=api_key, sleep=sleep, clock=clock, now=now)
    info = {
        "started_utc": iso(started),
        "rounds_planned": rounds,
        "interval_s": interval_s,
        "sizes_usd": list(sizes),
        "pairs": [list(p) for p in PAIRS],
        "tokens": {s: {"address": t.address, "decimals": t.decimals} for s, t in TOKENS.items()},
        "uniswap_v3": {"factory": UNISWAP_V3_FACTORY, "quoter_v2": QUOTER_V2, "fee_tiers": list(FEE_TIERS)},
        "reference_tier": REFERENCE_TIER,
        "direct_gas_overhead": DIRECT_GAS_OVERHEAD,
        "direct_tx_bytes": DIRECT_TX_BYTES,
        "sanity_bps": SANITY_BPS,
        "code_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "rounds_done": 0,
    }
    try:
        verify_tokens(probe)
    except VerificationError as exc:
        recorder.write_json("verification.json", {"tokens": str(exc), "direct": None})
        recorder.write_manifest({**info, "stopped": f"token verification failed: {exc}"})
        raise
    mids = {}
    for product in PRODUCTS:
        mid = _maybe(lambda p=product: parse_ticker(json_of(probe.ticker(p))).mid)
        if mid is not None:
            mids[product] = mid
    direct = verify_direct(probe, mids)
    recorder.write_json("verification.json", {"tokens": "ok", "direct": direct.__dict__})
    out(f"raw folder: {raw_dir}")
    out("direct route: " + ("verified" if direct.enabled else f"LEFT OUT ({direct.reason})"))
    for rnd in range(rounds):
        t0 = clock()
        record, samples = run_round(probe, rnd, direct, sizes)
        recorder.append_jsonl("rounds.jsonl", [record])
        recorder.append_jsonl("samples.jsonl", samples)
        info["rounds_done"] = rnd + 1
        recorder.write_manifest(info)
        try:  # the table is derived from the raw files; a failure here must not stop the sampling
            table = build_table(raw_dir)
            write_table(table, raw_dir, data_dir / "swap_costs")
        except Exception as exc:  # noqa: BLE001 - reported, and `parse` rebuilds the table later
            out(f"round {rnd + 1}/{rounds}: table not built ({type(exc).__name__}: {exc}); raw files kept")
        else:
            done = table[table["round"] == rnd]
            out(f"round {rnd + 1}/{rounds} at {record['ts_utc']}: {int(done['ok'].sum())} of {len(done)} rows priced")
        if rnd + 1 < rounds:
            sleep(max(0.0, interval_s - (clock() - t0)))
    return raw_dir


def _sizes(text: str) -> list[int]:
    try:
        sizes = [int(s) for s in text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"sizes must be a comma list of whole USD amounts: {text!r}") from exc
    if not sizes or min(sizes) <= 0:
        raise argparse.ArgumentTypeError(f"sizes must be positive: {text!r}")
    return sizes


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m lab.data.swap_costs", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="verify, then sample 0x and the direct pool in rounds")
    s.add_argument("--rounds", type=int, default=6)
    s.add_argument("--interval-min", type=float, default=10.0, help="minutes between round starts")
    s.add_argument("--sizes", type=_sizes, default=list(SIZES_USD), help="USD sizes, comma separated")
    s.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    r = sub.add_parser("parse", help="rebuild a run's table from its raw folder")
    r.add_argument("raw_dir", type=Path)
    r.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    m = sub.add_parser("summary", help="medians and worst cases of one or more tables")
    m.add_argument("tables", type=Path, nargs="+")
    return p


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    args = parser().parse_args(argv)
    if args.cmd == "sample":
        api_key = os.environ.get("ZEROX_API_KEY") or "proxy-injected"
        try:
            raw_dir = sample(args.data_dir, args.rounds, args.interval_min * 60, args.sizes, client=client, api_key=api_key)
        except VerificationError as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            return 2
        print(f"table: {args.data_dir / 'swap_costs' / (raw_dir.name + '.parquet')}")
        return 0
    if args.cmd == "parse":
        path = write_table(build_table(args.raw_dir), args.raw_dir, args.data_dir / "swap_costs")
        print(f"table: {path}")
        return 0
    table = pd.concat([pd.read_parquet(t) for t in args.tables], ignore_index=True)
    print(summarize(table).to_markdown(index=False, floatfmt=".2f"))
    print()
    print(gap_summary(table).to_markdown(index=False, floatfmt=".2f"))
    print()
    print(source_summary(table).to_markdown(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
