"""lab/data/swap_costs.py: the read-only swap-cost probe (0x price, a direct Uniswap v3 pool, the Coinbase mid).

No network: every request goes to a fake of the three hosts behind ``httpx.MockTransport`` (``World``), and an
autouse fixture makes any real HTTP request fail the test. Recorded responses (Base and Coinbase, 2026-11-25)
pin the parsing of real shapes; costs are computed by hand next to them. Selectors are recomputed with an
independent Keccak-256.
"""

from __future__ import annotations

import json
import math
import runpy
import sys
import warnings
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from math import isqrt
from pathlib import Path

import httpx
import pandas as pd
import pytest

from lab.data import swap_costs as sc

USDC, WETH, CBBTC = sc.TOKENS["USDC"], sc.TOKENS["WETH"], sc.TOKENS["cbBTC"]
FACTORY, QUOTER, ORACLE = sc.UNISWAP_V3_FACTORY.lower(), sc.QUOTER_V2.lower(), sc.GAS_PRICE_ORACLE.lower()
SECRET = "test-0x-key-7f3a91c4"  # the key the tests send; it must never appear in any output


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(self, request):
        raise AssertionError(f"a test tried the network: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


# ============================================================================ an independent Keccak-256

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
    0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
    0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]  # fmt: skip
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def keccak256(data: bytes) -> bytes:
    """Keccak-256 as Ethereum uses it (padding byte 0x01, not SHA-3's 0x06)."""
    msg = bytearray(data) + b"\x01"
    while len(msg) % 136:
        msg += b"\x00"
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), 136):
        for i in range(17):
            a[i % 5][i // 5] ^= int.from_bytes(msg[off + 8 * i : off + 8 * i + 8], "little")
        for rnd in range(24):
            c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
            d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
            a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
            b = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
            a = [[b[x][y] ^ (~b[(x + 1) % 5][y] & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
            a[0][0] ^= _RC[rnd]
    return b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


def test_the_keccak_used_here_is_keccak_256():
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256(b"transfer(address,uint256)").hex()[:8] == "a9059cbb"  # the ERC-20 selector everyone knows


def test_every_selector_is_the_keccak_of_its_signature():
    for signature, selector in sc.SELECTORS.items():
        assert keccak256(signature.encode()).hex()[:8] == selector, signature


# ============================================================================ recorded responses (2026-11-25)

REC_ZEROX_BUY_WETH = (  # 100 USDC -> WETH, block 62196699
    '{"allowanceTarget":"0x000000000022d473030f116ddee9f6b43ac78ba3","blockNumber":"62196699","buyAmount":'
    '"59208236868290872","buyToken":"0x4200000000000000000000000000000000000006","fees":{"integratorFee":null,'
    '"integratorFees":null,"zeroExFee":{"amount":"150000","token":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",'
    '"type":"volume"},"gasFee":null},"issues":{"allowance":null,"balance":{"token":'
    '"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","actual":"20705746","expected":"100000000"},'
    '"simulationIncomplete":false,"invalidSourcesPassed":[]},"liquidityAvailable":true,"minBuyAmount":'
    '"58616154499607963","mode":"exact-in","route":{"fills":[{"from":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",'
    '"to":"0x4200000000000000000000000000000000000006","source":"LunarBase","proportionBps":"10000"}],"tokens":'
    '[{"address":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","symbol":"USDC"},{"address":'
    '"0x4200000000000000000000000000000000000006","symbol":"WETH"}]},"sellAmount":"100000000","sellToken":'
    '"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","tokenMetadata":{"buyToken":{"buyTaxBps":"0","sellTaxBps":"0",'
    '"transferTaxBps":"0"},"sellToken":{"buyTaxBps":"0","sellTaxBps":"0","transferTaxBps":"0"}},'
    '"totalNetworkFee":"3226735460193","zid":"0x58cdaa028fbe3f817788928f","gas":"302246","gasPrice":"10625000"}'
)
REC_ZEROX_SELL_CBBTC = (  # 0.83852878 cbBTC -> USDC ($50,000), block 62196784: 0x's fee in the BUY token
    '{"allowanceTarget":"0x000000000022d473030f116ddee9f6b43ac78ba3","blockNumber":"62196784","buyAmount":'
    '"49927985515","buyToken":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","fees":{"integratorFee":null,'
    '"integratorFees":null,"zeroExFee":{"amount":"75004486","token":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",'
    '"type":"volume"},"gasFee":null},"issues":{"allowance":{"actual":"0","spender":'
    '"0x000000000022d473030f116ddee9f6b43ac78ba3"},"balance":{"token":"0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",'
    '"actual":"0","expected":"83852878"},"simulationIncomplete":false,"invalidSourcesPassed":[]},'
    '"liquidityAvailable":true,"minBuyAmount":"49428705660","mode":"exact-in","route":{"fills":[{"from":'
    '"0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf","to":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","source":'
    '"Kipseli","proportionBps":"5500"},{"from":"0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf","to":'
    '"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","source":"Hanji","proportionBps":"4500"}],"tokens":[{"address":'
    '"0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf","symbol":"cbBTC"},{"address":'
    '"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","symbol":"USDC"}]},"sellAmount":"83852878","sellToken":'
    '"0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf","tokenMetadata":{"buyToken":{"buyTaxBps":"0","sellTaxBps":"0",'
    '"transferTaxBps":"0"},"sellToken":{"buyTaxBps":"0","sellTaxBps":"0","transferTaxBps":"0"}},'
    '"totalNetworkFee":"25718437087266","zid":"0xe8943f83d6f81c25eb456e02","gas":"2808658","gasPrice":"9150000"}'
)
REC_TICKER_BTC = (
    '{"ask":"59600.03","bid":"59600.02","volume":"15388.63656104","trade_id":1147519061,"price":"59601.22",'
    '"size":"0.00418518","time":"2026-11-25T18:01:41.495297162Z","rfq_volume":"309.809630"}'
)
REC_QUOTE_100_USDC_WETH_FEE_100 = (  # QuoterV2 at block 0x3b50bdb
    "0x00000000000000000000000000000000000000000000000000d3b6feb3586a39"
    "00000000000000000000000000000000000000000002af3cf76775b26a09b949"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000015116"
)
REC_SLOT0_WETH_500 = (  # slot0 of the WETH/USDC 0.05% pool; the tick (word 2) is negative
    "0x00000000000000000000000000000000000000000002af20d78de3f761427248"
    "fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffceaa9"
    "0000000000000000000000000000000000000000000000000000000000001929"
    "0000000000000000000000000000000000000000000000000000000000001a2c"
    "0000000000000000000000000000000000000000000000000000000000001a2c"
    "0000000000000000000000000000000000000000000000000000000000000044"
    "0000000000000000000000000000000000000000000000000000000000000001"
)
REC_SYMBOL_USDC = (
    "0x0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000004"
    "5553444300000000000000000000000000000000000000000000000000000000"
)
REC_L1_FEE_400_BYTES = "0x00000000000000000000000000000000000000000000000000000002ece218e6"


# ============================================================================ a fake Base, 0x and Coinbase


def word(n: int) -> str:
    return f"{n:064x}"


def abi_string(text: str) -> str:
    data = text.encode().hex()
    return "0x" + word(32) + word(len(text.encode())) + data.ljust(64 * max(1, math.ceil(len(data) / 64)), "0")


def ok(result: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def rpc_error(code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}


BY_SELECTOR = {sel: sig for sig, sel in sc.SELECTORS.items()}


class Clock:
    """Fake time: ``sleep`` advances it, so pacing shows in the recorded timestamps."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds

    def now(self) -> datetime:
        return datetime(2026, 11, 25, 12, 0, tzinfo=UTC) + timedelta(seconds=self.t)


class World:
    """The three hosts. Coinbase mids are exact binary numbers (ETH 2000, BTC 50000), so the module's float
    mid equals the exact one. 0x prices every trade at its 15 bps fee plus ``zerox_other_bps``; the direct pool
    at its fee tier plus ``impact_bps``; pools sit ``premium_bps`` above the Coinbase mid. Every request is
    logged with the headers it carried. ``queue(key, ...)`` answers a request first with the given items."""

    def __init__(self) -> None:
        self.mid = {"ETH-USD": Fraction(2000), "BTC-USD": Fraction(50000)}
        self.half_spread = {"ETH-USD": Fraction(1, 4), "BTC-USD": Fraction(1, 2)}
        self.head = 1000
        self.zerox_block = 1000
        self.zerox_other_bps = Fraction(5)
        self.impact_bps = Fraction(1)
        self.premium_bps = {"WETH": Fraction(0), "cbBTC": Fraction(0)}
        self.gas_price = 6_000_000
        self.l1_fee = 10**10
        self.tokens = {t.address.lower(): (t.symbol, t.decimals) for t in sc.TOKENS.values()}
        self.pools: dict[str, dict] = {}
        for k, coin in enumerate(sc.COINS):
            t0, t1 = sc.ordered(sc.TOKENS[coin], USDC)
            for j, tier in enumerate(sc.FEE_TIERS):
                self.pools[f"0x{0xA000 + 16 * k + j:040x}"] = {
                    "coin": coin,
                    "factory()": int(FACTORY, 16),
                    "fee()": tier,
                    "token0()": int(t0.address, 16),
                    "token1()": int(t1.address, 16),
                }
        self.registered = {(p["coin"], p["fee()"]): a for a, p in self.pools.items()}
        self.code = set(self.tokens) | {FACTORY, QUOTER, ORACLE} | set(self.pools)
        self.quoter = {"factory()": int(FACTORY, 16), "WETH9()": int(WETH.address, 16)}
        self.script: dict[str, list] = {}
        self.log: list[dict] = []

    def client(self) -> httpx.Client:
        return sc.make_client(httpx.MockTransport(self))

    def queue(self, key: str, *items) -> None:
        self.script.setdefault(key, []).extend(items)

    def pool(self, coin: str, tier: int) -> str:
        return self.registered[(coin, tier)]

    # -- dispatch
    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.method == "POST" else None
        self.log.append(
            {"method": request.method, "url": str(request.url), "headers": dict(request.headers), "json": body}
        )
        host = request.url.host
        if host == sc.COINBASE_HOST:
            key = "ticker:" + request.url.path.split("/")[2]
        elif host == sc.ZEROX_HOST:
            key = "zerox"
        elif body["method"] == "eth_call":
            key = f"call:{body['params'][0]['to'].lower()}:{body['params'][0]['data'][2:10]}"
        else:
            key = f"rpc:{body['method']}"
        if self.script.get(key):
            item = self.script[key].pop(0)
            if isinstance(item, Exception):
                raise item
            return item if isinstance(item, httpx.Response) else httpx.Response(200, json=item)
        if host == sc.COINBASE_HOST:
            return httpx.Response(200, json=self.ticker(request.url.path.split("/")[2]))
        if host == sc.ZEROX_HOST:
            return httpx.Response(200, json=self.zerox(dict(request.url.params)))
        return httpx.Response(200, json=self.rpc(body))

    # -- Coinbase
    def ticker(self, product: str) -> dict:
        m, h = self.mid[product], self.half_spread[product]
        return {"bid": str(float(m - h)), "ask": str(float(m + h)), "time": "2026-11-25T12:00:00Z", "price": "1"}

    # -- prices
    def usd(self, token: sc.Token) -> Fraction:
        return Fraction(1) if token.product is None else self.mid[token.product]

    def zerox(self, params: dict) -> dict:
        sell, buy = sc.BY_ADDRESS[params["sellToken"].lower()], sc.BY_ADDRESS[params["buyToken"].lower()]
        amount = int(params["sellAmount"])
        value_in = Fraction(amount, 10**sell.decimals) * self.usd(sell)
        value_out = value_in * (1 - (15 + self.zerox_other_bps) / 10_000)
        buy_amount = math.floor(value_out / self.usd(buy) * 10**buy.decimals)
        fee = math.floor(amount * Fraction(15, 10_000)) if sell is USDC else math.floor(value_in * Fraction(15, 10_000) * 10**6)
        return {
            "blockNumber": str(self.zerox_block),
            "buyAmount": str(buy_amount),
            "buyToken": buy.address.lower(),
            "sellAmount": str(amount),
            "sellToken": sell.address.lower(),
            "fees": {"integratorFee": None, "zeroExFee": {"amount": str(fee), "token": USDC.address.lower(), "type": "volume"}, "gasFee": None},
            "liquidityAvailable": True,
            "route": {"fills": [{"source": "Uniswap_V3", "proportionBps": "6000"}, {"source": "Kipseli", "proportionBps": "4000"}]},
            "gas": "300000",
            "gasPrice": "10000000",
            "totalNetworkFee": str(300_000 * 10_000_000 + 10**10),
        }

    def sqrt_price(self, coin: str) -> int:
        token = sc.TOKENS[coin]
        p = self.usd(token) * (1 + self.premium_bps[coin] / 10_000)
        t0, _ = sc.ordered(token, USDC)
        raw = p * 10**6 / 10**token.decimals if t0 is token else 1 / p * 10**token.decimals / 10**6
        return isqrt(math.floor(raw * 2**192))

    def quote(self, args: list[int]) -> str:
        sell, buy = sc.BY_ADDRESS[f"0x{args[0]:040x}"], sc.BY_ADDRESS[f"0x{args[1]:040x}"]
        value_in = Fraction(args[2], 10**sell.decimals) * self.usd(sell)
        value_out = value_in * (1 - (Fraction(args[3], 100) + self.impact_bps) / 10_000)
        out = math.floor(value_out / self.usd(buy) * 10**buy.decimals)
        return "0x" + word(out) + word(0) + word(1) + word(100_000)

    # -- Base
    def rpc(self, body: dict) -> dict:
        method, params = body["method"], body["params"]
        if method == "eth_gasPrice":
            return ok(hex(self.gas_price))
        if method == "eth_getCode":
            return ok("0x6080604052" if params[0].lower() in self.code else "0x")
        call, tag = params
        if tag != "latest" and int(tag, 16) > self.head:
            return rpc_error(-32001, f"block not found: {tag}")
        to, sig = call["to"].lower(), BY_SELECTOR[call["data"][2:10]]
        args = [int(call["data"][10 + 64 * i : 74 + 64 * i], 16) for i in range((len(call["data"]) - 10) // 64)]
        if to in self.tokens:
            symbol, decimals = self.tokens[to]
            return ok(abi_string(symbol) if sig == "symbol()" else "0x" + word(decimals))
        if to == FACTORY:  # getPool(token0, token1, fee): by registration, whatever the pool says about itself
            coin = next(c for c in sc.COINS if int(sc.TOKENS[c].address, 16) in args[:2])
            addr = self.registered.get((coin, args[2]))
            return ok("0x" + word(int(addr, 16) if addr else 0))
        if to == QUOTER:
            return ok(self.quote(args) if sig.startswith("quoteExactInputSingle") else "0x" + word(self.quoter[sig]))
        if to == ORACLE:
            return ok("0x" + word(self.l1_fee))
        pool = self.pools[to]
        if sig == "slot0()":
            return ok("0x" + word(self.sqrt_price(pool["coin"])) + word(0) * 6)
        return ok("0x" + word(pool[sig]))

    # -- what was asked
    def requests(self, host: str) -> list[dict]:
        return [r for r in self.log if httpx.URL(r["url"]).host == host]


def run(tmp_path: Path, world: World, rounds: int = 1, sizes=(100, 1000), interval: float = 600.0, **kw):
    clock = Clock()
    out: list[str] = []
    raw = sc.sample(
        tmp_path, rounds, interval, sizes, client=world.client(), api_key=SECRET, sleep=clock.sleep,
        clock=clock.clock, now=clock.now, out=out.append, **kw,
    )  # fmt: skip
    return raw, clock, out


def files(raw: Path, kind: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(raw.glob(f"*-{kind}.json"))]


def table_of(tmp_path: Path, raw: Path) -> pd.DataFrame:
    return pd.read_parquet(tmp_path / "swap_costs" / f"{raw.name}.parquet")


def row(table: pd.DataFrame, pair: str, size: int, route: str, rnd: int = 0) -> pd.Series:
    sel = table[(table["pair"] == pair) & (table["size_usd"] == size) & (table["route"] == route) & (table["round"] == rnd)]
    assert len(sel) == 1
    return sel.iloc[0]


# ============================================================================ only the listed requests


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "https://api.0x.org/swap/permit2/price"),
        ("POST", "https://mainnet.base.org"),
        ("POST", "https://mainnet.base.org/"),
        ("GET", "https://api.exchange.coinbase.com/products/BTC-USD/ticker"),
        ("GET", "https://api.exchange.coinbase.com/products/ETH-USD/ticker"),
        ("GET", "https://api.0x.org:443/swap/permit2/price"),
    ],
)
def test_the_listed_requests_pass(method, url):
    assert sc.check_request(method, url).host in sc.ALLOWED


@pytest.mark.parametrize(
    ("method", "url", "message"),
    [
        ("GET", "https://api.0x.org/swap/permit2/quote", "not allowed on api.0x.org"),  # returns a signable tx
        ("GET", "https://api.0x.org/swap/allowance-holder/quote", "not allowed on api.0x.org"),
        ("GET", "https://api.0x.org/swap/allowance-holder/price", "not allowed on api.0x.org"),
        ("POST", "https://api.0x.org/swap/permit2/price", "not allowed on api.0x.org"),
        ("GET", "https://mainnet.base.org/", "not allowed on mainnet.base.org"),
        ("POST", "https://mainnet.base.org/rpc", "not allowed on mainnet.base.org"),
        ("GET", "https://api.exchange.coinbase.com/products/SOL-USD/ticker", "not allowed on api.exchange"),
        ("GET", "https://api.exchange.coinbase.com/products/BTC-USD/candles", "not allowed on api.exchange"),
        ("POST", "https://api.exchange.coinbase.com/orders", "not allowed on api.exchange"),
        ("GET", "http://api.0x.org/swap/permit2/price", "only plain https"),
        ("GET", "https://user:pw@api.0x.org/swap/permit2/price", "only plain https"),
        ("GET", "https://api.0x.org:8443/swap/permit2/price", "only plain https"),
        ("GET", "https://api.0x.org.example.com/swap/permit2/price", "host not allowed"),
        ("POST", "https://base-mainnet.example.com/", "host not allowed"),
    ],
)
def test_every_other_request_is_refused(method, url, message):
    with pytest.raises(sc.DisallowedRequestError, match=message):
        sc.check_request(method, url)


def probe_for(tmp_path: Path, world: World, **kw) -> sc.Probe:
    clock = Clock()
    return sc.Probe(
        world.client(), sc.RawRecorder(tmp_path, [SECRET]), api_key=SECRET, sleep=clock.sleep, clock=clock.clock,
        now=clock.now, **kw,
    )  # fmt: skip


@pytest.mark.parametrize(
    "method", ["eth_sendRawTransaction", "eth_sendTransaction", "eth_sign", "personal_sign", "eth_blockNumber", ""]
)
def test_rpc_methods_off_the_list_are_refused_before_any_traffic(tmp_path, method):
    world = World()
    probe = probe_for(tmp_path, world)
    with pytest.raises(sc.DisallowedRequestError, match="RPC method not allowed"):
        probe.rpc("x", method, [])
    with pytest.raises(sc.DisallowedRequestError):
        probe.exchange("x", "GET", "https://api.0x.org/swap/permit2/quote")
    assert world.log == [] and list(tmp_path.iterdir()) == []


def test_redirects_are_never_followed(tmp_path):
    world = World()
    world.queue("ticker:ETH-USD", httpx.Response(302, headers={"location": "https://example.com/"}))
    ex = probe_for(tmp_path, world).ticker("ETH-USD")
    assert ex.status == 302 and len(world.log) == 1
    with pytest.raises(sc.ParseError, match="HTTP 302"):
        sc.json_of(ex)


def test_make_client_sends_the_generic_user_agent_and_follows_no_redirect():
    client = sc.make_client(httpx.MockTransport(lambda r: httpx.Response(200)))
    assert client.headers["user-agent"] == "strategy-lab/0.1" and client.follow_redirects is False


# ============================================================================ the full run on the fake world


def test_a_run_records_everything_and_prices_every_sample_by_hand(tmp_path):
    world = World()
    raw, clock, out = run(tmp_path, world, rounds=2, sizes=(100, 1000))
    assert raw == tmp_path / "raw" / "swap_costs" / "20261125T120000Z"
    table = table_of(tmp_path, raw)
    assert len(table) == 2 * 4 * 2 * 2 and table["ok"].all()  # rounds x pairs x sizes x routes
    assert out[1] == "direct route: verified" and out[-1].startswith("round 2/2")

    # 0x, USDC -> WETH $1000: 998 USD of WETH back (20 bps), 15 bps of it 0x's fee (1.5 USDC)
    zx = row(table, "USDC->WETH", 1000, "0x")
    assert zx["sell_amount"] == 1000 and zx["buy_amount"] == pytest.approx(0.499, rel=1e-15)
    assert zx["cost_bps"] == pytest.approx(20, abs=1e-9) and zx["fee_bps"] == pytest.approx(15, abs=1e-12)
    assert zx["fee_token"] == "USDC" and zx["other_bps"] == pytest.approx(5, abs=1e-9)
    assert zx["gap_bps"] == pytest.approx(0, abs=1e-9) and zx["impact_bps"] == pytest.approx(5, abs=1e-9)
    gas_usd = (300_000 * 10_000_000 + 10**10) / 1e18 * 2000  # totalNetworkFee x ETH mid
    assert zx["gas_usd"] == pytest.approx(gas_usd, rel=1e-12) and zx["l1_fee_wei"] == 10**10
    assert zx["gas_bps"] == pytest.approx(gas_usd / 1000 * 1e4, rel=1e-12)
    assert zx["total_bps"] == pytest.approx(20 + gas_usd / 1000 * 1e4, abs=1e-9)
    assert zx["block"] == "1000" and zx["sources"] == "Uniswap_V3:6000;Kipseli:4000"
    assert zx["unknown_sources"] == "Kipseli"

    # direct, same trade: the 1 bp pool wins (1 bp fee + 1 bp impact); gas (100,000 + 81,000) x 6e6 wei + L1
    d = row(table, "USDC->WETH", 1000, "uniswap_v3")
    assert d["fee_tier"] == 100 and d["fee_bps"] == 1 and d["cost_bps"] == pytest.approx(2, abs=1e-9)
    assert d["gas_units"] == 181_000 and d["gas_price_wei"] == 6_000_000 and d["l1_fee_wei"] == 10**10
    assert d["gas_usd"] == pytest.approx((181_000 * 6_000_000 + 10**10) / 1e18 * 2000, rel=1e-12)
    assert d["pool_gap_bps"] == pytest.approx(0, abs=1e-9) and d["impact_bps"] == pytest.approx(1, abs=1e-9)
    assert d["ticks_crossed"] == 1 and d["block"] == "1000"

    # selling cbBTC: $100 at the BTC mid 50000 is 200,000 sats; 0x's fee is paid in USDC (the buy token)
    s = row(table, "cbBTC->USDC", 100, "0x")
    assert s["sell_amount"] == pytest.approx(0.002, rel=1e-15) and s["value_in_usd"] == pytest.approx(100)
    assert s["fee_bps"] == pytest.approx(15, abs=1e-9) and s["cost_bps"] == pytest.approx(20, abs=1e-6)

    # the table is the raw files: rebuilt from them it is the same, and the manifest holds every file's hash
    sc.write_table(sc.build_table(raw), raw, tmp_path / "again")
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "again" / f"{raw.name}.parquet"), table)
    manifest = json.loads((raw / "manifest.json").read_text())
    on_disk = {p.name for p in raw.iterdir()} - {"manifest.json"}
    assert set(manifest["files"]) == on_disk and manifest["rounds_done"] == 2
    assert manifest["code_sha256"] == sc.sha256_bytes(Path(sc.__file__).read_bytes())
    meta = json.loads((tmp_path / "swap_costs" / f"{raw.name}.json").read_text())
    assert meta["rows"] == meta["rows_ok"] == 32
    assert (tmp_path / "swap_costs" / f"{raw.name}.csv").is_file()


def test_rounds_start_interval_apart_and_each_host_is_paced(tmp_path):
    world = World()
    raw, clock, _ = run(tmp_path, world, rounds=3, sizes=(100,), interval=600.0)
    starts = [datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00")) for r in sc.read_jsonl(raw / "rounds.jsonl")]
    gaps = [(b - a).total_seconds() for a, b in zip(starts, starts[1:], strict=False)]
    assert gaps == [pytest.approx(600.0, abs=1e-6)] * 2
    for kind, host in (("zerox_price", sc.ZEROX_HOST), ("ticker", sc.COINBASE_HOST), ("quote", sc.RPC_HOST)):
        ts = [datetime.fromisoformat(e["ts_utc"].replace("Z", "+00:00")) for e in files(raw, kind)]
        gap = min((b - a).total_seconds() for a, b in zip(ts, ts[1:], strict=False))
        assert gap >= sc.MIN_INTERVAL[host] - 2e-6  # timestamps are kept to the microsecond
    assert sc.MIN_INTERVAL[sc.ZEROX_HOST] >= 1.0  # 0x allows about 5 a second; we stay at 1


def test_no_header_is_ever_written_or_printed_and_the_key_goes_to_0x_only(tmp_path, capsys):
    world = World()
    world.queue("zerox", httpx.Response(401, json={"message": f"invalid key {SECRET}"}))  # echoed back
    world.queue("zerox", httpx.ConnectError(f"proxy said no to {SECRET}"), *[httpx.ConnectError("again")] * 2)
    raw, _, out = run(tmp_path, world, sizes=(100, 1000))
    zerox = world.requests(sc.ZEROX_HOST)
    assert zerox and all(r["headers"]["0x-api-key"] == SECRET and r["headers"]["0x-version"] == "v2" for r in zerox)
    others = [r for r in world.log if httpx.URL(r["url"]).host != sc.ZEROX_HOST]
    assert others and not any("0x-api-key" in r["headers"] or SECRET in json.dumps(r) for r in others)
    printed = capsys.readouterr()
    for text in ["\n".join(out), printed.out, printed.err]:
        assert SECRET not in text and "0x-api-key" not in text.lower()
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(written) > 50
    for p in written:
        data = p.read_bytes()
        assert SECRET.encode() not in data and b"0x-api-key" not in data.lower(), p
    envelopes = [json.loads(p.read_text()) for p in sorted(raw.glob("0*.json"))]
    assert all(set(e["request"]) == {"method", "url", "params", "json"} for e in envelopes)
    scrubbed = [e for e in envelopes if e["scrubbed"]]
    assert [e["kind"] for e in scrubbed] == ["zerox_price", "zerox_price"]
    assert "<redacted>" in scrubbed[0]["body"] and "<redacted>" in scrubbed[1]["error"]
    table = table_of(tmp_path, raw)
    errors = table.loc[table["route"] == "0x", "error"].dropna().tolist()
    assert errors == ['0x: HTTP 401: {"message":"invalid key <redacted>"}', "0x: ConnectError: again"]


def test_the_0x_request_is_the_price_endpoint_with_no_taker(tmp_path):
    world = World()
    run(tmp_path, world, sizes=(100,))
    for r in world.requests(sc.ZEROX_HOST):
        url = httpx.URL(r["url"])
        assert r["method"] == "GET" and url.path == "/swap/permit2/price"
        assert set(url.params) == {"chainId", "sellToken", "buyToken", "sellAmount"} and url.params["chainId"] == "8453"
    rpc = world.requests(sc.RPC_HOST)
    assert {r["json"]["method"] for r in rpc} == {"eth_call", "eth_gasPrice", "eth_getCode"}
    assert all(r["method"] == "POST" for r in rpc)


def test_sizes_become_base_units_by_hand():
    assert sc.sell_amount_units(USDC, 1000, 1.0) == 1_000_000_000
    assert sc.sell_amount_units(USDC, 100, 1234.5) == 100_000_000  # the mid does not matter for USDC
    assert sc.sell_amount_units(CBBTC, 50_000, 59_400.0) == 84_175_084  # 0.8417508417... cbBTC, rounded down
    assert sc.sell_amount_units(WETH, 1000, 1670.515) == math.floor(Fraction(1000) / Fraction(1670.515) * 10**18)
    assert sc.sell_amount_units(WETH, 100, 2000.0) == 5 * 10**16


# ============================================================================ parsing


def test_abi_words_by_hand():
    assert sc.word_address(USDC.address) == "000000000000000000000000833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert sc.word_uint(500) == "0" * 61 + "1f4"
    assert sc.calldata("fee()") == "0xddca3f43"
    data = sc.quote_calldata(USDC, WETH, 100_000_000, 100)
    assert data == (
        "0xc6a5026a000000000000000000000000833589fcd6edb6e08f4c7c32d4f71b54bda02913"
        "0000000000000000000000004200000000000000000000000000000000000006"
        "0000000000000000000000000000000000000000000000000000000005f5e100"
        "0000000000000000000000000000000000000000000000000000000000000064"
        "0000000000000000000000000000000000000000000000000000000000000000"
    )  # the calldata of the recorded quote request
    assert sc.words("0x" + word(7) + word(9), 2) == [7, 9]
    assert sc.as_address(int(WETH.address, 16)) == WETH.address.lower()
    for bad in ("0x1234", "0x" + "g" * 40):
        with pytest.raises(ValueError, match="not an address"):
            sc.word_address(bad)
    for bad in (-1, 2**256):
        with pytest.raises(ValueError, match="not a uint256"):
            sc.word_uint(bad)
    for bad in ("0x" + word(1), "0x" + "zz" * 64):
        with pytest.raises(sc.ParseError, match="expected 2 words"):
            sc.words(bad, 2)
    with pytest.raises(sc.ParseError, match="not an address word"):
        sc.as_address(2**160)


def test_quantities_by_hand():
    assert sc.quantity("0x5b8d80") == 6_000_000  # a recorded eth_gasPrice: 0.006 gwei
    assert sc.quantity("0x0") == 0
    for bad in ("0x", "0x" + "1" * 65, "0xgg"):
        with pytest.raises(sc.ParseError, match="not a quantity"):
            sc.quantity(bad)


def test_strings_by_hand():
    assert sc.decode_string(REC_SYMBOL_USDC) == "USDC"
    assert sc.decode_string(abi_string("cbBTC")) == "cbBTC"
    with pytest.raises(sc.ParseError, match="bad string offset"):
        sc.decode_string("0x" + word(31) + word(4))
    with pytest.raises(sc.ParseError, match="bad string offset"):
        sc.decode_string("0x" + word(64) + word(4))
    with pytest.raises(sc.ParseError, match="shorter than its length"):
        sc.decode_string("0x" + word(32) + word(40) + "55" * 8)
    with pytest.raises(sc.ParseError, match="not UTF-8"):
        sc.decode_string("0x" + word(32) + word(1) + "ff".ljust(64, "0"))


def test_recorded_quote_and_slot0_by_hand():
    q = sc.parse_quote(REC_QUOTE_100_USDC_WETH_FEE_100, 100)
    assert q == sc.DirectQuote(100, int("d3b6feb3586a39", 16), 0, 0x15116)
    assert q.amount_out == 59_592_425_132_812_857 and q.gas_estimate == 86_294  # 0.0596 WETH for 100 USDC
    with pytest.raises(sc.ParseError, match="fee 500: zero output"):
        sc.parse_quote("0x" + word(0) * 4, 500)
    (s,) = sc.words(REC_SLOT0_WETH_500, 1)
    by_hand = Fraction(s * s, 2**192) * 10**12  # (sqrtPriceX96 / 2^96)^2 x 10^(18 - 6): USDC per WETH
    assert sc.pool_price_usd(s, WETH) == float(by_hand) and 1677 < float(by_hand) < 1678


def test_pool_prices_by_hand():
    # cbBTC/USDC: token0 USDC (6), token1 cbBTC (8). sqrtP = 2^90: (2^-6)^2 / 100 cbBTC per USDC -> 409,600 USD
    assert sc.pool_price_usd(2**90, CBBTC) == 409_600.0
    # WETH/USDC: token0 WETH (18), token1 USDC (6). sqrtP = 2^76: 2^-40 x 10^12 = 5^12 / 2^28 USD per WETH
    assert sc.pool_price_usd(2**76, WETH) == 5**12 / 2**28
    with pytest.raises(sc.ParseError, match="zero pool price"):
        sc.pool_price_usd(0, WETH)
    assert sc.ordered(USDC, WETH) == (WETH, USDC) and sc.ordered(USDC, CBBTC) == (USDC, CBBTC)


def test_tickers():
    t = sc.parse_ticker(json.loads(REC_TICKER_BTC))
    assert (t.bid, t.ask, t.mid) == (59600.02, 59600.03, (59600.02 + 59600.03) / 2)
    for bad in ({}, {"bid": "x", "ask": "1", "time": "t"}, None):
        with pytest.raises(sc.ParseError, match="malformed ticker"):
            sc.parse_ticker(bad)
    for bid, ask in (("2", "1"), ("0", "1"), ("nan", "1"), ("1", "inf")):
        with pytest.raises(sc.ParseError, match="bad bid/ask"):
            sc.parse_ticker({"bid": bid, "ask": ask, "time": "t"})


def test_recorded_0x_prices_parse():
    p = sc.parse_zerox(json.loads(REC_ZEROX_BUY_WETH), USDC, WETH, 100_000_000)
    assert p == sc.ZeroXPrice(
        buy_amount=59_208_236_868_290_872, fee_amount=150_000, fee_token=USDC.address.lower(), gas=302_246,
        gas_price=10_625_000, total_network_fee=3_226_735_460_193, block=62_196_699, fills=(("LunarBase", 10_000),),
    )  # fmt: skip
    q = sc.parse_zerox(json.loads(REC_ZEROX_SELL_CBBTC), CBBTC, USDC, 83_852_878)
    assert q.fee_token == USDC.address.lower() and q.fills == (("Kipseli", 5500), ("Hanji", 4500))
    no_fee = json.loads(REC_ZEROX_BUY_WETH) | {"fees": {"zeroExFee": None}}
    assert sc.parse_zerox(no_fee, USDC, WETH, 100_000_000).fee_token is None
    assert sc.parse_zerox(json.loads(REC_ZEROX_BUY_WETH) | {"fees": None}, USDC, WETH, 100_000_000).fee_amount == 0
    with pytest.raises(sc.ParseError, match="another request"):
        sc.parse_zerox(json.loads(REC_ZEROX_BUY_WETH), USDC, WETH, 100_000_001)
    with pytest.raises(sc.ParseError, match="another request"):
        sc.parse_zerox(json.loads(REC_ZEROX_BUY_WETH), USDC, CBBTC, 100_000_000)
    for bad in ({"liquidityAvailable": False, "zid": "0x1"}, [], {"buyAmount": "1"}):
        with pytest.raises(sc.ParseError, match="no liquidity"):
            sc.parse_zerox(bad, USDC, WETH, 1)
    broken = json.loads(REC_ZEROX_BUY_WETH)
    del broken["gas"]
    with pytest.raises(sc.ParseError, match="malformed price: KeyError"):
        sc.parse_zerox(broken, USDC, WETH, 100_000_000)


def test_exchanges_and_rpc_answers():
    assert sc.json_of(sc.Exchange(1, 200, b'{"a": 1}', None)) == {"a": 1}
    with pytest.raises(sc.ParseError, match="ReadTimeout: slow"):
        sc.json_of(sc.Exchange(1, None, None, "ReadTimeout: slow"))
    with pytest.raises(sc.ParseError, match="HTTP 500: oops"):
        sc.json_of(sc.Exchange(1, 500, b"oops", None))
    with pytest.raises(sc.ParseError, match="not JSON: <html>"):
        sc.json_of(sc.Exchange(1, 200, b"<html>", None))
    rpc = lambda obj: sc.Exchange(1, 200, json.dumps(obj).encode(), None)  # noqa: E731
    assert sc.rpc_result(rpc(ok("0x01"))) == "0x01"
    with pytest.raises(sc.ParseError, match="RPC error -32001: block not found"):
        sc.rpc_result(rpc(rpc_error(-32001, "block not found")))
    with pytest.raises(sc.ParseError, match="^weird$"):
        sc.rpc_result(rpc({"error": "weird"}))
    with pytest.raises(sc.ParseError, match="not a JSON-RPC answer"):
        sc.rpc_result(rpc([1]))
    for result in (None, 12, "12"):
        with pytest.raises(sc.ParseError, match="not a hex result"):
            sc.rpc_result(rpc({"result": result}))


# ============================================================================ costs by hand on recorded responses


def recorded_rows(zerox_body: str, sell, buy, amount: int, ticker: dict, *, slot0=None, quotes=None, ctx=None,
                  direct=False) -> list[dict]:  # fmt: skip
    exchanges = {1: sc.Exchange(1, 200, json.dumps(ticker).encode(), None), 2: sc.Exchange(2, 200, zerox_body.encode(), None)}
    seq = 3
    slot0_seqs, quote_seqs = {}, {}
    for target, items in ((slot0_seqs, slot0 or {}), (quote_seqs, quotes or {})):
        for tier, item in items.items():
            exchanges[seq] = item if isinstance(item, sc.Exchange) else sc.Exchange(seq, 200, json.dumps(ok(item)).encode(), None)
            target[tier] = seq
            seq += 1
    rec = {
        "round": 0, "sample": 0, "ts_utc": "t", "sell": sell.symbol, "buy": buy.symbol, "size_usd": 1,
        "ticker": 1, "sell_amount": str(amount), "zerox": 2, "tag": "0x3b50bdb", "slot0": slot0_seqs or None,
        "quotes": quote_seqs,
    }  # fmt: skip
    ctx = ctx or {"eth_mid": None, "gas_price": None, "l1_fee": None}
    route = sc.DirectRoute(direct)
    return sc.sample_rows(rec, ctx, route, exchanges.__getitem__, "run")


def test_0x_costs_by_hand_on_a_recorded_price():
    ticker = {"bid": "1677.35", "ask": "1677.37", "time": "t"}
    mid = (1677.35 + 1677.37) / 2
    ctx = {"eth_mid": mid, "gas_price": None, "l1_fee": None}
    (r,) = recorded_rows(REC_ZEROX_BUY_WETH, USDC, WETH, 100_000_000, ticker, ctx=ctx)
    value_out = Fraction(59_208_236_868_290_872, 10**18) * Fraction(mid)  # 0.0592... WETH at the ETH mid
    cost = (100 - value_out) / 100 * 10_000
    assert r["ok"] and r["value_in_usd"] == 100.0 and r["cb_mid"] == mid
    assert r["cost_bps"] == pytest.approx(float(cost), rel=1e-12) and 68 < r["cost_bps"] < 69
    assert r["fee_bps"] == pytest.approx(15.0, abs=1e-12) and r["fee_token"] == "USDC"  # 0.15 USDC of 100
    assert r["other_bps"] == pytest.approx(float(cost) - 15, rel=1e-12)
    assert r["gap_bps"] is None and r["impact_bps"] is None  # no slot0 recorded: no gap, no split
    gas_usd = 3_226_735_460_193 / 1e18 * mid
    assert r["gas_usd"] == pytest.approx(gas_usd, rel=1e-12) and r["gas_bps"] == pytest.approx(gas_usd / 100 * 1e4)
    assert r["total_bps"] == pytest.approx(float(cost) + gas_usd / 100 * 1e4, rel=1e-12)
    assert r["l1_fee_wei"] == 3_226_735_460_193 - 302_246 * 10_625_000 == 15_371_710_193
    assert (r["block"], r["sources"], r["unknown_sources"]) == ("62196699", "LunarBase:10000", "LunarBase")


def test_0x_fee_in_the_buy_token_by_hand():
    ticker = {"bid": "59628.24", "ask": "59628.25", "time": "t"}
    mid = (59628.24 + 59628.25) / 2
    (r,) = recorded_rows(REC_ZEROX_SELL_CBBTC, CBBTC, USDC, 83_852_878, ticker)
    value_in = 0.83852878 * mid
    assert r["value_in_usd"] == pytest.approx(value_in, rel=1e-15)
    assert r["fee_bps"] == pytest.approx(75.004486 / value_in * 1e4, rel=1e-12)  # 75.004486 USDC
    assert r["cost_bps"] == pytest.approx((value_in - 49_927.985515) / value_in * 1e4, rel=1e-9)
    assert r["gas_usd"] is None and r["total_bps"] is None  # no ETH mid for this round: gas is unknown, not 0
    assert r["unknown_sources"] == "Hanji;Kipseli"
    no_fee = json.loads(REC_ZEROX_SELL_CBBTC) | {"fees": {"zeroExFee": None}}
    (r,) = recorded_rows(json.dumps(no_fee), CBBTC, USDC, 83_852_878, ticker)
    assert r["ok"] and r["fee_bps"] == 0.0 and r["fee_token"] is None
    assert r["other_bps"] == pytest.approx(r["cost_bps"], abs=0)


def test_a_0x_fee_in_another_token_fails_the_row():
    body = json.loads(REC_ZEROX_BUY_WETH)
    body["fees"]["zeroExFee"]["token"] = CBBTC.address.lower()
    (r,) = recorded_rows(json.dumps(body), USDC, WETH, 100_000_000, {"bid": "1", "ask": "1", "time": "t"})
    assert not r["ok"] and r["error"] == f"0x: 0x fee in an unexpected token {CBBTC.address.lower()}"


def sqrt_price_of_weth(usd: int) -> int:
    raw = Fraction(usd * 10**6, 10**18)  # USDC base units per wei: token1 per token0
    return isqrt(raw.numerator * 2**192 // raw.denominator)


def test_direct_costs_by_hand():
    # Sell 1 WETH at the Coinbase mid 2000. Fee 100: 1999.60 USDC (best); fee 500: 1999.50; fee 3000: reverted.
    # The 0.01% pool's mid is 2001 (5 bps above Coinbase), the 0.05% (reference) and 0.3% pools' 2002 (10 bps).
    ticker = {"bid": "1999.75", "ask": "2000.25", "time": "t"}
    premium = {
        t: float((Fraction(sqrt_price_of_weth(usd) ** 2, 2**192) * 10**12 / 2000 - 1) * 10_000)
        for t, usd in (("100", 2001), ("500", 2002), ("3000", 2002))
    }
    quotes = {
        "100": "0x" + word(1_999_600_000) + word(0) + word(3) + word(120_000),
        "500": "0x" + word(1_999_500_000) + word(0) + word(0) + word(90_000),
        "3000": sc.Exchange(99, 200, json.dumps(rpc_error(3, "execution reverted")).encode(), None),
    }
    slot0 = {t: "0x" + word(sqrt_price_of_weth(usd)) for t, usd in (("500", 2002), ("100", 2001), ("3000", 2002))}
    ctx = {"eth_mid": 2000.0, "gas_price": 6_000_000, "l1_fee": 10**10}
    zx, d = recorded_rows(
        json.dumps(World().zerox({"sellToken": WETH.address, "buyToken": USDC.address, "sellAmount": str(10**18)})),
        WETH, USDC, 10**18, ticker, slot0=slot0, quotes=quotes, ctx=ctx, direct=True,
    )  # fmt: skip
    assert premium["100"] == pytest.approx(5, abs=1e-9) and premium["500"] == pytest.approx(10, abs=1e-9)
    near = lambda x: pytest.approx(x, abs=1e-9)  # noqa: E731 - float bps of a ratio near 1 lose ~1e-12
    assert zx["base_mid_usd"] == pytest.approx(2002, rel=1e-15) and zx["base_premium_bps"] == near(premium["500"])
    assert zx["gap_bps"] == near(-premium["500"]) and d["gap_bps"] == near(-premium["500"])  # selling: Base dearer helps
    assert zx["impact_bps"] == near(zx["other_bps"] + premium["500"])
    assert [d[f"premium_{t}_bps"] for t in ("100", "500", "3000")] == [near(premium[t]) for t in ("100", "500", "3000")]
    assert d["ok"] and d["fee_tier"] == 100 and d["fee_bps"] == 1 and d["ticks_crossed"] == 3
    assert d["value_out_usd"] == 1999.6 and d["cost_bps"] == pytest.approx(2.0, abs=1e-12)
    assert d["other_bps"] == pytest.approx(1.0, abs=1e-12)
    # the direct row's impact is against its own pool's mid (2001), not the reference pool's
    assert d["pool_gap_bps"] == near(-premium["100"]) and d["impact_bps"] == near(1.0 + premium["100"])
    assert d["gas_units"] == 120_000 + 81_000
    assert d["gas_usd"] == pytest.approx((201_000 * 6_000_000 + 10**10) / 1e18 * 2000, rel=1e-12)  # $0.002432
    assert d["total_bps"] == pytest.approx(2.0 + d["gas_usd"] / 2000 * 1e4, rel=1e-12)
    assert d["block"] == str(0x3B50BDB)


def test_a_direct_row_without_a_quote_or_a_pool_mid():
    ticker = {"bid": "1999.75", "ask": "2000.25", "time": "t"}
    body = json.dumps(World().zerox({"sellToken": USDC.address, "buyToken": WETH.address, "sellAmount": "100000000"}))
    failed = sc.Exchange(9, 200, json.dumps(rpc_error(3, "execution reverted")).encode(), None)
    _, d = recorded_rows(body, USDC, WETH, 100_000_000, ticker, quotes={"100": failed, "500": failed}, direct=True)
    assert not d["ok"] and d["error"] == "uniswap_v3: fee 100: RPC error 3: execution reverted; fee 500: RPC error 3: execution reverted"
    _, d = recorded_rows(body, USDC, WETH, 100_000_000, ticker, direct=True)
    assert d["error"] == "uniswap_v3: no quote"
    q = {"100": "0x" + word(5 * 10**16) + word(0) * 3}
    zx, d = recorded_rows(body, USDC, WETH, 100_000_000, ticker, quotes=q, slot0={"500": failed}, direct=True)
    assert d["ok"] and d["pool_gap_bps"] is None and d["impact_bps"] is None and d["gas_usd"] is None
    assert d["block"] == str(0x3B50BDB) and zx["gap_bps"] is None and zx["base_mid_usd"] is None


# ============================================================================ verification


def test_tokens_and_the_direct_route_verify_on_the_fake_world(tmp_path):
    world = World()
    probe = probe_for(tmp_path, world, min_interval={h: 0.0 for h in sc.ALLOWED})
    sc.verify_tokens(probe)
    route = sc.verify_direct(probe, {"ETH-USD": 2000.0, "BTC-USD": 50000.0})
    assert route.enabled and route.reason is None
    assert route.pools == {c: {str(t): world.pool(c, t) for t in sc.FEE_TIERS} for c in sc.COINS}
    assert route.checks == {"WETH": pytest.approx(2.0, abs=1e-9), "cbBTC": pytest.approx(2.0, abs=1e-9)}


def _token(world: World, symbol: str) -> str:
    return sc.TOKENS[symbol].address.lower()


TOKEN_BREAKS = {
    "wrong symbol": (lambda w: w.tokens.__setitem__(_token(w, "USDC"), ("USDbC", 6)), "symbol 'USDbC' and decimals 6"),
    "wrong decimals": (lambda w: w.tokens.__setitem__(_token(w, "WETH"), ("WETH", 6)), "expected 'WETH' and 18"),
    "no code": (lambda w: w.code.discard(_token(w, "cbBTC")), "cbBTC: no contract code"),
    "rpc fails": (lambda w: w.queue("rpc:eth_getCode", rpc_error(-32603, "internal")), "USDC: could not read"),
    "symbol fails": (lambda w: w.queue(f"call:{_token(w, 'USDC')}:95d89b41", ok("0x" + word(1))), "could not read"),
}


@pytest.mark.parametrize("name", TOKEN_BREAKS)
def test_a_token_that_does_not_verify_stops_the_run_before_any_price(tmp_path, name):
    world = World()
    TOKEN_BREAKS[name][0](world)
    with pytest.raises(sc.VerificationError, match=TOKEN_BREAKS[name][1]):
        run(tmp_path, world)
    raw = tmp_path / "raw" / "swap_costs" / "20261125T120000Z"
    assert TOKEN_BREAKS[name][1] in json.loads((raw / "verification.json").read_text())["tokens"]
    assert "token verification failed" in json.loads((raw / "manifest.json").read_text())["stopped"]
    assert world.requests(sc.ZEROX_HOST) == [] and world.requests(sc.COINBASE_HOST) == []
    assert sc.build_table(raw).empty  # the stopped run still parses: nothing was priced


def _quote_fails(world: World) -> None:
    world.queue(f"call:{QUOTER}:c6a5026a", *[rpc_error(3, "execution reverted")] * 3)


DIRECT_BREAKS = {
    "factory code": (lambda w: w.code.discard(FACTORY), "factory: no contract code"),
    "quoter code": (lambda w: w.code.discard(QUOTER), "QuoterV2: no contract code"),
    "quoter factory": (lambda w: w.quoter.__setitem__("factory()", 0x1234), "QuoterV2 factory() is 0x0000"),
    "quoter weth": (lambda w: w.quoter.__setitem__("WETH9()", 0x1234), "QuoterV2 WETH9() is 0x0000"),
    "no pool": (lambda w: w.registered.pop(("WETH", 100)), "no WETH/USDC pool with code at fee 100"),
    "pool code": (lambda w: w.code.discard(w.pool("cbBTC", 3000)), "no cbBTC/USDC pool with code at fee 3000"),
    "pool fee": (lambda w: w.pools[w.pool("WETH", 500)].__setitem__("fee()", 501), "fee() is 0x1f5, expected 0x1f4"),
    "pool factory": (lambda w: w.pools[w.pool("WETH", 500)].__setitem__("factory()", 7), "factory() is 0x7"),
    "pool token0": (lambda w: w.pools[w.pool("cbBTC", 100)].__setitem__("token0()", 7), "token0() is 0x7"),
    "pool token1": (lambda w: w.pools[w.pool("cbBTC", 100)].__setitem__("token1()", 7), "token1() is 0x7"),
    "getPool fails": (lambda w: w.queue(f"call:{FACTORY}:1698ee82", rpc_error(-32000, "x")), "RPC error -32000"),
    "quote far off": (lambda w: setattr(w, "impact_bps", Fraction(250)), "251.0 bps from the Coinbase mid (limit 200.0)"),
    "quote far better": (lambda w: setattr(w, "impact_bps", Fraction(-250)), "-249.0 bps from the Coinbase mid"),
    "no quote": (_quote_fails, "QuoterV2 gave no $100 USDC->WETH quote"),
    "no mid": (lambda w: w.queue("ticker:BTC-USD", httpx.Response(404)), "no Coinbase mid for BTC-USD"),
}


@pytest.mark.parametrize("name", DIRECT_BREAKS)
def test_a_direct_route_that_does_not_verify_is_left_out_and_0x_is_still_sampled(tmp_path, name):
    world = World()
    DIRECT_BREAKS[name][0](world)
    raw, _, out = run(tmp_path, world, sizes=(100,))
    direct = json.loads((raw / "verification.json").read_text())["direct"]
    assert direct["enabled"] is False and DIRECT_BREAKS[name][1] in direct["reason"]
    assert out[1].startswith("direct route: LEFT OUT (") and DIRECT_BREAKS[name][1] in out[1]
    assert files(raw, "quote") == [] and files(raw, "slot0") == []  # nothing priced on an unverified route
    table = table_of(tmp_path, raw)
    assert set(table["route"]) == {"0x"} and len(table) == 4 and table["ok"].all()
    assert table["gap_bps"].isna().all()


def test_the_sanity_limit_is_200_bps_from_the_coinbase_mid(tmp_path):
    assert sc.SANITY_BPS == 200.0
    # with the 1 bp tier's fee: 199.9 and 200.1 bps from the mid (the rounding of the quote is ~1e-12 bps)
    for impact, enabled in ((Fraction(1989, 10), True), (Fraction(1991, 10), False)):
        world = World()
        world.impact_bps = impact
        route = sc.verify_direct(probe_for(tmp_path / str(impact), world), {"ETH-USD": 2000.0, "BTC-USD": 50000.0})
        assert route.enabled is enabled


# ============================================================================ failed requests and fallbacks


def test_a_429_is_retried_and_every_attempt_is_recorded(tmp_path):
    world = World()
    world.queue("zerox", httpx.Response(429, json={"reason": "slow down"}), httpx.Response(503))
    raw, clock, _ = run(tmp_path, world, sizes=(100,))
    attempts = files(raw, "zerox_price")
    assert [e["status"] for e in attempts[:3]] == [429, 503, 200] and [e["attempt"] for e in attempts[:3]] == [0, 1, 2]
    assert 1.0 in clock.sleeps and 2.0 in clock.sleeps  # backoff 1 s, then 2 s
    assert table_of(tmp_path, raw)["ok"].all()


def test_failed_requests_are_recorded_with_their_error(tmp_path):
    world = World()
    world.queue("zerox", httpx.Response(400, json={"name": "INPUT_INVALID"}))  # sample 0: USDC -> WETH $100
    world.queue("zerox", {"liquidityAvailable": False, "zid": "0x2"})  # sample 1: USDC -> WETH $1000
    raw, _, _ = run(tmp_path, world, sizes=(100, 1000))
    table = table_of(tmp_path, raw)
    assert row(table, "USDC->WETH", 100, "0x")["error"] == '0x: HTTP 400: {"name":"INPUT_INVALID"}'
    assert row(table, "USDC->WETH", 1000, "0x")["error"].startswith("0x: no liquidity available")
    # the direct route still priced both, at the latest block (0x gave none)
    assert row(table, "USDC->WETH", 100, "uniswap_v3")["ok"]
    assert row(table, "USDC->WETH", 1000, "uniswap_v3")["block"] == "latest"
    assert all(e["status"] in (200, 400) for e in files(raw, "zerox_price"))


def test_a_failed_ticker_ends_the_sample_and_nothing_is_priced_without_a_mid(tmp_path):
    good = {"bid": "1999.75", "ask": "2000.25", "time": "t"}
    world = World()
    world.queue("ticker:ETH-USD", good, good, httpx.Response(404))  # verification, the round, then sample 0
    raw, _, _ = run(tmp_path, world, sizes=(100,))
    table = table_of(tmp_path, raw)
    failed = table[table["sample"] == 0]
    assert len(failed) == 2 and not failed["ok"].any()
    assert set(failed["error"]) == {"coinbase ticker: HTTP 404: "}
    assert table.loc[table["sample"] > 0, "ok"].all()
    sample0 = sc.read_jsonl(raw / "samples.jsonl")[0]
    assert (sample0["zerox"], sample0["quotes"], sample0["sell_amount"], sample0["slot0"]) == (None, {}, None, None)
    assert len(files(raw, "zerox_price")) == 3  # samples 1-3 only


def test_round_level_failures_leave_gas_unknown_never_zero(tmp_path):
    world = World()
    world.queue("rpc:eth_gasPrice", rpc_error(-32603, "internal"))
    raw, _, _ = run(tmp_path, world, sizes=(100,))
    table = table_of(tmp_path, raw)
    d = table[table["route"] == "uniswap_v3"]
    assert d["ok"].all() and d["gas_usd"].isna().all() and d["total_bps"].isna().all()
    assert table.loc[table["route"] == "0x", "gas_usd"].notna().all()  # 0x reports its own network fee
    world = World()
    world.queue(f"call:{ORACLE}:f1c7a58b", rpc_error(-32000, "x"))
    world.queue("ticker:ETH-USD", {"bid": "1999.75", "ask": "2000.25", "time": "t"}, httpx.Response(500), httpx.Response(500), httpx.Response(500))
    raw, _, _ = run(tmp_path / "b", world, sizes=(100,))
    table = table_of(tmp_path / "b", raw)
    assert table["ok"].all() and table["gas_usd"].isna().all() and table["eth_mid"].isna().all()


def test_a_transport_error_is_recorded_and_the_row_says_so(tmp_path):
    world = World()
    world.queue("zerox", *[httpx.ReadTimeout("timed out")] * 3)
    raw, _, _ = run(tmp_path, world, sizes=(100,))
    attempts = files(raw, "zerox_price")[:3]
    assert [e["status"] for e in attempts] == [None, None, None]
    assert all(e["error"] == "ReadTimeout: timed out" and e["body"] is None for e in attempts)
    assert row(table_of(tmp_path, raw), "USDC->WETH", 100, "0x")["error"] == "0x: ReadTimeout: timed out"


def test_the_pool_reads_are_pinned_to_0x_s_block_or_fall_back_to_latest(tmp_path):
    world = World()
    world.zerox_block = 999
    raw, _, _ = run(tmp_path, world, sizes=(100,))
    tags = {e["request"]["json"]["params"][1] for k in ("slot0", "quote") for e in files(raw, k)}
    assert tags == {hex(999)}
    assert set(table_of(tmp_path, raw)["block"]) == {"999"}

    world = World()
    world.zerox_block = 1005  # 0x is ahead of this node: the pinned read fails, and is asked again at latest
    raw, _, _ = run(tmp_path / "b", world, sizes=(100,))
    slot0 = files(raw, "slot0")
    assert [e["request"]["json"]["params"][1] for e in slot0[:4]] == [hex(1005), "latest", "latest", "latest"]
    assert {e["request"]["json"]["params"][1] for e in files(raw, "quote")} == {"latest"}
    table = table_of(tmp_path / "b", raw)
    assert set(table.loc[table["route"] == "uniswap_v3", "block"]) == {"latest"} and table["ok"].all()
    assert all(s["tag"] == "latest" for s in sc.read_jsonl(raw / "samples.jsonl"))


def test_a_body_that_is_not_utf8_is_kept_byte_for_byte(tmp_path):
    world = World()
    world.queue("ticker:ETH-USD", {"bid": "1999.75", "ask": "2000.25", "time": "t"}, {"bid": "1999.75", "ask": "2000.25", "time": "t"})
    world.queue("ticker:ETH-USD", httpx.Response(200, content=b"\xff\xfe\x00"))
    raw, _, _ = run(tmp_path, world, sizes=(100,))
    env = next(e for e in files(raw, "ticker") if "body_b64" in e)
    assert env["body"] is None and env["body_sha256"] == sc.sha256_bytes(b"\xff\xfe\x00")
    path = next(p for p in raw.glob("*-ticker.json") if "body_b64" in p.read_text())
    assert sc.load_exchange(path).body == b"\xff\xfe\x00"
    assert row(table_of(tmp_path, raw), "USDC->WETH", 100, "0x")["error"].startswith("coinbase ticker: not JSON")


# ============================================================================ the raw folder is the record


def test_a_changed_or_missing_raw_file_is_refused(tmp_path):
    raw, _, _ = run(tmp_path, World(), sizes=(100,))
    target = sorted(raw.glob("*-zerox_price.json"))[0]
    target.write_text(target.read_text().replace('"status": 200', '"status": 201'))
    with pytest.raises(sc.ChecksumError, match="missing or changed"):
        sc.build_table(raw)
    target.unlink()
    with pytest.raises(sc.ChecksumError, match="missing or changed"):
        sc.build_table(raw)


def test_files_of_a_round_cut_short_are_not_read(tmp_path):
    raw, _, _ = run(tmp_path, World(), sizes=(100,))
    before = sc.build_table(raw)
    (raw / "99999-zerox_price.json").write_text("not even json")  # a killed round's last file, never listed
    pd.testing.assert_frame_equal(sc.build_table(raw), before)


def test_a_run_never_writes_into_another_run_s_folder(tmp_path):
    run(tmp_path, World(), sizes=(100,))
    with pytest.raises(FileExistsError):
        run(tmp_path, World(), sizes=(100,))


@pytest.mark.parametrize(("rounds", "interval", "sizes"), [(0, 1.0, (100,)), (1, -1.0, (100,)), (1, 1.0, ()), (1, 1.0, (0,))])
def test_bad_run_arguments_are_refused(tmp_path, rounds, interval, sizes):
    with pytest.raises(ValueError, match="rounds >= 1"):
        sc.sample(tmp_path, rounds, interval, sizes, client=World().client())
    assert not (tmp_path / "raw").exists()


def test_a_table_that_cannot_be_built_does_not_stop_the_sampling(tmp_path, monkeypatch):
    def broken(raw_dir):
        raise KeyError("boom")

    monkeypatch.setattr(sc, "build_table", broken)
    raw, _, out = run(tmp_path, World(), rounds=2, sizes=(100,))
    assert out[-2:] == [
        "round 1/2: table not built (KeyError: 'boom'); raw files kept",
        "round 2/2: table not built (KeyError: 'boom'); raw files kept",
    ]
    assert len(sc.read_jsonl(raw / "samples.jsonl")) == 8 and len(sc.read_jsonl(raw / "rounds.jsonl")) == 2


def test_the_recorder_appends_and_lists_its_files(tmp_path):
    rec = sc.RawRecorder(tmp_path, ["", "k3y"])
    assert rec.secrets == ["k3y"]
    rec.append_jsonl("a.jsonl", [{"x": 1}])
    rec.append_jsonl("a.jsonl", [{"x": 2}, {"x": 3}])
    assert sc.read_jsonl(tmp_path / "a.jsonl") == [{"x": 1}, {"x": 2}, {"x": 3}]
    assert sc.read_jsonl(tmp_path / "missing.jsonl") == []
    (tmp_path / "b.json.tmp").write_text("half written")
    rec.write_manifest({"run": 1})
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest == {"run": 1, "files": {"a.jsonl": sc.sha256_bytes((tmp_path / "a.jsonl").read_bytes())}}
    seq = rec.record("k", {}, None, None, "boom k3y", datetime(2026, 1, 1, tzinfo=UTC), 0.5, 0)
    env = json.loads((tmp_path / f"{seq:05d}-k.json").read_text())
    assert (env["error"], env["scrubbed"], env["ts_utc"]) == ("boom <redacted>", True, "2026-01-01T00:00:00.000000Z")


# ============================================================================ summaries and the command line


def test_summaries_by_hand():
    rows = []
    for i, (cost, ok_, gas) in enumerate([(10.0, True, 0.01), (20.0, True, 0.03), (None, False, None)]):
        r = dict.fromkeys(sc.COLUMNS)
        r.update(run="r", round=i, sample=0, pair="USDC->WETH", coin="WETH", size_usd=100, route="0x", ok=ok_,
                 cost_bps=cost, total_bps=None if cost is None else cost + 1, fee_bps=15.0 if ok_ else None,
                 other_bps=None if cost is None else cost - 15, gap_bps=1.0 if ok_ else None, gas_usd=gas,
                 base_premium_bps=-1.0 + i, unknown_sources="Kipseli;Hanji" if ok_ else None)  # fmt: skip
        rows.append(r)
    r = dict(rows[0], route="uniswap_v3", pair="WETH->USDC", coin="WETH", sample=1, cost_bps=3.0, total_bps=3.5,
             base_premium_bps=4.0, unknown_sources=None)  # fmt: skip
    same_sample = dict(rows[0], route="uniswap_v3", cost_bps=4.0, unknown_sources=None)  # round 0's sample 0 again
    table = pd.DataFrame([*rows, r, same_sample], columns=list(sc.COLUMNS))
    s = sc.summarize(table)
    assert list(zip(s["pair"], s["route"], strict=True)) == [
        ("USDC->WETH", "0x"), ("USDC->WETH", "uniswap_v3"), ("WETH->USDC", "uniswap_v3"),
    ]  # fmt: skip
    first = s.iloc[0]
    assert (first["n"], first["failed"], first["cost_med"], first["cost_worst"]) == (3, 1, 15.0, 20.0)
    assert (first["total_med"], first["total_worst"], first["fee_med"], first["other_med"]) == (16.0, 21.0, 15.0, 0.0)
    assert (first["gas_usd_med"], first["gas_usd_worst"]) == (pytest.approx(0.02), 0.03)
    # 90th percentiles, interpolated between the two priced samples: a + 0.9 (b - a)
    assert (first["cost_p90"], first["total_p90"], first["other_p90"]) == (19.0, 20.0, 4.0)
    assert first["gas_usd_p90"] == pytest.approx(0.028)
    g = sc.gap_summary(table)  # one value per sample: rows 0-2 are three rounds, the 4th another sample, the 5th a repeat
    assert g.to_dict("records") == [{"coin": "WETH", "n": 4, "median": 0.5, "min": -1.0, "max": 4.0}]
    src = sc.source_summary(table)
    assert src.to_dict("records") == [
        {"source": "Hanji", "pair": "USDC->WETH", "samples": 2},
        {"source": "Kipseli", "pair": "USDC->WETH", "samples": 2},
    ]
    assert list(sc.source_summary(table.iloc[3:]).columns) == ["source", "pair", "samples"]
    assert sc.source_summary(table.iloc[3:]).empty


def test_the_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sc, "MIN_INTERVAL", {h: 0.0 for h in sc.ALLOWED})
    monkeypatch.setenv("ZEROX_API_KEY", SECRET)
    world = World()
    argv = ["sample", "--rounds", "1", "--interval-min", "0", "--sizes", "100", "--data-dir", str(tmp_path)]
    assert sc.main(argv, client=world.client()) == 0
    assert all(r["headers"]["0x-api-key"] == SECRET for r in world.requests(sc.ZEROX_HOST))
    printed = capsys.readouterr().out
    assert "direct route: verified" in printed and SECRET not in printed
    (raw,) = (tmp_path / "raw" / "swap_costs").iterdir()
    table_path = tmp_path / "swap_costs" / f"{raw.name}.parquet"
    assert f"table: {table_path}" in printed
    before = pd.read_parquet(table_path)
    table_path.unlink()
    assert sc.main(["parse", str(raw), "--data-dir", str(tmp_path)]) == 0
    pd.testing.assert_frame_equal(pd.read_parquet(table_path), before)
    capsys.readouterr()
    assert sc.main(["summary", str(table_path), str(table_path)]) == 0
    summary = capsys.readouterr().out
    assert "| USDC->WETH  |        100 | 0x         |   2 |" in summary and "Kipseli" in summary

    monkeypatch.delenv("ZEROX_API_KEY")
    world = World()
    other = ["--data-dir", str(tmp_path / "no-env")]
    assert sc.main(argv[:-2] + other, client=world.client()) == 0  # without the variable the proxy injects the key
    assert world.requests(sc.ZEROX_HOST)
    assert all(r["headers"]["0x-api-key"] == "proxy-injected" for r in world.requests(sc.ZEROX_HOST))
    world = World()
    world.tokens[USDC.address.lower()] = ("USDC", 18)
    capsys.readouterr()
    assert sc.main(argv[:-2] + ["--data-dir", str(tmp_path / "stopped")], client=world.client()) == 2
    assert "stopped: " in capsys.readouterr().err and world.requests(sc.ZEROX_HOST) == []

    for bad in ("abc", "0", "100,-5"):
        with pytest.raises(SystemExit):
            sc.parser().parse_args(["sample", "--sizes", bad])

    monkeypatch.setattr(sys, "argv", ["swap_costs", "summary", str(table_path)])
    with warnings.catch_warnings(), pytest.raises(SystemExit) as exc:
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: the module is already imported by this test
        runpy.run_module("lab.data.swap_costs", run_name="__main__")
    assert exc.value.code == 0
