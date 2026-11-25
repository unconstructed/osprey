"""The backtest contract (``lab/runner/interface.py``) on a NautilusTrader v2 ``BacktestEngine``.

**What Nautilus does here.** Every run builds one engine, one simulated venue (a cash account, spot only: no
borrowing, no leverage), one instrument (COINX/USDX) and one strategy, runs it and disposes of it (AGENTS.md
"Running many simulations", rule 1). Nautilus holds the book: the USD cash and the coin units are Nautilus
account balances, every order is a Nautilus market order, every fill and its commission come from the Nautilus
matching engine and :class:`lab.costs.fees.DexFeeModel`. The result columns are read off those balances.

**Execution model (hard rule 4).** Each bar is fed as two quotes: its open, 1 ns after the previous bar's close,
and its close, at the bar's close time. At the close quote of bar t the rule decides a target weight from data
up to that close. At the open quote of bar t+1 the strategy sizes the order from the account and that open
(as the production trade router sizes each swap from the wallet at execution), and the market order fills at
that quote. A decision at the last close is never filled. Highs, lows and volumes are not fed: no rule here
reads them for fills, and ``bars`` is validated in full before the run.

**The rules are the reference rules.** :func:`run` takes a rule written for ``lab.runner.reference``
(``dip_buy``, ``constant_mix``, ``scheduled``, ...). The rule checks its params and bars and builds its decision
function as usual; :func:`decider` takes that function instead of letting the reference engine run it, and
the Nautilus strategy calls it at every close with the state Nautilus's own fills give (position, entry bar,
entry fill price, exit bar). So both runners make their decisions with one piece of code (the owner's
option B, docs/app/technical.md "Strategy settings"), and the parity test compares the accounting alone.

**Precision.** Cash, coin units, prices and fees are fixed-point with 12 decimals (``PRECISION``): a quantity
is rounded down to 1e-12 units, so a book of 10,000 USD at a price of 100,000 is off by at most 1e-7 USD per
fill. The contract tolerance for this runner (``TOL``) is written down from that.
"""

from __future__ import annotations

import functools
import math
import threading
from collections.abc import Callable, Mapping
from decimal import ROUND_DOWN, Decimal

import numpy as np
import pandas as pd
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.config import BacktestEngineConfig, StrategyConfig
from nautilus_trader.model import (
    AccountType,
    Currency,
    CurrencyPair,
    CurrencyType,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.trading import Strategy

from lab.costs.fees import DexFeeModel, fee_usd, intended_tag
from lab.runner import reference
from lab.runner.reference import Costs, _fills_frame, _State

__all__ = ["PRECISION", "TOL", "NautilusRunError", "decider", "run", "wrap"]

PRECISION = 12
TOL = 1e-9  # contract tolerance: fixed-point round-off of 1e-12 units and prices, far below any cost
# A leg smaller than this share of the book is fixed-point round-off, not a trade: the book's weight after a fill
# is off its target by up to ~1e-12 x price / book, and a rule that keeps a weight (constant_mix, band 0) would
# otherwise send that difference back as an order and pay gas for it. The reference runner trades such legs in
# float arithmetic (TESTING.md bugs #36 and #61): mostly on flat prices, and rarely when a moving price comes back
# to within ~1e-9 of the last fill's weight (once in 1,750 hourly 50/50 rebalances, 2017-2022). This runner never does.
MIN_LEG = 1e-9
_STEP = Decimal(1).scaleb(-PRECISION)
USDX = Currency("USDX", PRECISION, 0, "lab dollar (USDC)", CurrencyType.CRYPTO)
COINX = Currency("COINX", PRECISION, 0, "lab coin", CurrencyType.CRYPTO)
VENUE = Venue("BASEDEX")
INSTRUMENT_ID = InstrumentId(Symbol("COINX/USDX"), VENUE)
_BOOK_SIZE = Quantity(1e12, PRECISION)  # unlimited top-of-book size: a fill never walks the book


class NautilusRunError(RuntimeError):
    """The engine did something the runner does not allow (a rejected order, a partial fill, a fee mismatch)."""


# ------------------------------------------------------------------------------------- the rule's decisions


class _Captured(Exception):  # noqa: N818 (a control-flow signal, not an error)
    def __init__(self, decide, costs):
        super().__init__()
        self.decide, self.costs = decide, costs


_CAPTURE_LOCK = threading.Lock()


def decider(rule: Callable, params: Mapping, bars: pd.DataFrame, costs: Costs | None):
    """``(decide, costs)`` of a reference rule: the rule validates ``params`` and ``bars`` (``ValueError``
    otherwise) and builds its decision function, which is returned instead of being run by the reference engine.
    ``costs`` is the rule's resolved cost model (``config/costs.yaml`` when None)."""

    def grab(_bars, resolved, decide):
        raise _Captured(decide, resolved)

    with _CAPTURE_LOCK:
        original = reference._simulate
        reference._simulate = grab
        try:
            rule(params, bars, costs) if costs is not None else rule(params, bars)
        except _Captured as captured:
            return captured.decide, captured.costs
        finally:
            reference._simulate = original
    raise ValueError(
        f"{getattr(rule, '__name__', rule)!r} is not a reference rule (it never reached the engine)"
    )


# ------------------------------------------------------------------------------------------- the strategy


def _units(x: float | Decimal) -> Quantity:
    """A non-negative quantity rounded DOWN to the instrument's precision."""
    return Quantity.from_str(
        str(
            max(Decimal(repr(x)) if isinstance(x, float) else x, Decimal(0)).quantize(
                _STEP, rounding=ROUND_DOWN
            )
        )
    )


def _affordable(cash: Money, fee: float, open_price: float) -> Decimal:
    """The most coin units the cash can buy at the open, after the fee, in the engine's own fixed-point
    arithmetic (the price and the fee as Nautilus rounds them, one step of the currency held back for the
    rounding of the notional). A full buy (target 1) is capped here, so cash never goes below 0."""
    price = Decimal(str(Price(open_price, PRECISION)))
    paid = Decimal(str(Money(fee, USDX).as_decimal())) + _STEP
    return (Decimal(str(cash.as_decimal())) - paid) / price


class _RuleStrategy(Strategy):
    def setup(self, opens, closes, index, decide, costs: Costs) -> _RuleStrategy:
        """Nautilus strategies are built from a config only, so the run's data come in here."""
        self.opens, self.closes, self.index = opens, closes, index
        self.decide, self.costs = decide, costs
        n = len(closes)
        self.cash_close = [0.0] * n
        self.coin_close = [0.0] * n
        self.pre = {}  # bar t -> (cash, coin, v_open, drifted, intended_usd, expected_fee) of a fill at its open
        self.fills = {}  # client order id -> list of (qty, px, commission)
        self.order_bar = {}
        self.problems: list[str] = []
        self.error: BaseException | None = None
        self.state = _State()
        self.target: float | None = None
        self.t_close = -1
        return self

    def on_start(self) -> None:
        self.subscribe_quotes(INSTRUMENT_ID)

    def cash_money(self) -> Money:
        return self.portfolio.account(VENUE).balance_total(USDX)

    def _balances(self) -> tuple[float, float]:
        account = self.portfolio.account(VENUE)
        return float(account.balance_total(USDX)), float(account.balance_total(COINX))

    def on_quote(self, quote: QuoteTick) -> None:
        if self.error is not None:
            return
        try:
            if quote.ts_event == self.index[self.t_close + 1]:
                self._on_close(self.t_close + 1)
            else:
                self._on_open(self.t_close + 1)
        except Exception as exc:  # re-raised by run() as itself, not as an engine error
            self.error = exc

    def _on_open(self, t: int) -> None:
        if self.target is None:
            return
        cash, coin = self._balances()
        o = self.opens[t]
        v_open = cash + coin * o
        drifted = coin * o / v_open
        traded = abs(self.target - drifted)
        if traded <= MIN_LEG:
            return
        intended = traded * v_open
        fee = fee_usd(self.costs, intended)
        k = fee / v_open
        if k >= 1.0:
            raise ValueError(
                f"costs of the fill on {pd.Timestamp(self.index[t], tz='UTC')} are {k:.1%} of a portfolio worth "
                f"{v_open:.4g} USD: it cannot pay them (raise capital_usd or check the cost model)"
            )
        want = self.target * (v_open - fee) / o  # coin units that hold exactly the target after the fee
        if self.target == 0.0:
            side, qty = OrderSide.SELL, Quantity(coin, PRECISION)
        elif want > coin:
            side = OrderSide.BUY
            qty = _units(min(Decimal(repr(want - coin)), _affordable(self.cash_money(), fee, o)))
        else:
            side, qty = OrderSide.SELL, _units(coin - want)
        if float(qty) == 0.0:  # a round-off leg below 1e-12 units: nothing Nautilus can trade
            return
        order = self.order_factory.market(INSTRUMENT_ID, side, qty, tags=[intended_tag(intended)])
        self.pre[t] = (cash, coin, v_open, drifted, intended, fee)
        self.order_bar[order.client_order_id] = t
        self.submit_order(order)

    def _on_close(self, t: int) -> None:
        self.t_close = t
        cash, coin = self._balances()
        self.cash_close[t], self.coin_close[t] = cash, coin
        c = self.closes[t]
        value = cash + coin * c
        # The rule sees the weight to the book's 12 decimals: below that it is fixed-point noise that differs
        # between cost models, and a rule on a knife edge (constant_mix with band 0 on a flat bar) must decide
        # the same with and without costs, as the reference does.
        self.state.position = round(coin * c / value, PRECISION)
        if t in self.pre:
            if self.pre[t][1] == 0.0:
                self.state.entry_bar, self.state.entry_price = t, self.opens[t]
            if coin == 0.0:
                self.state.entry_bar, self.state.exit_bar = None, t
        self.target = self.decide(t, self.state)

    def on_order_filled(self, event) -> None:
        self.fills.setdefault(event.client_order_id, []).append(
            (float(event.last_qty), float(event.last_px), float(event.commission))
        )

    def on_order_denied(self, event) -> None:
        self.problems.append(f"order denied: {event}")

    def on_order_rejected(self, event) -> None:
        self.problems.append(f"order rejected: {event}")


# ----------------------------------------------------------------------------------------------- running


def _quotes(opens: list[float], closes: list[float], index: list[int]) -> list[QuoteTick]:
    ticks = []
    for t, (o, c, ts) in enumerate(zip(opens, closes, index, strict=True)):
        if t > 0:  # bar 0's open can't fill anything (no decision exists yet)
            px = Price(o, PRECISION)
            ticks.append(
                QuoteTick(INSTRUMENT_ID, px, px, _BOOK_SIZE, _BOOK_SIZE, index[t - 1] + 1, index[t - 1] + 1)
            )
        px = Price(c, PRECISION)
        ticks.append(QuoteTick(INSTRUMENT_ID, px, px, _BOOK_SIZE, _BOOK_SIZE, ts, ts))
    return ticks


def _engine(costs: Costs) -> BacktestEngine:
    config = BacktestEngineConfig(
        trader_id=TraderId("LAB-001"),
        logging=LoggerConfig(stdout_level=LogLevel.ERROR, bypass_logging=True),
    )
    engine = BacktestEngine(config)
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.CASH,
        [Money(costs.capital_usd, USDX), Money(0, COINX)],
        fee_model=DexFeeModel(costs, USDX),
        use_message_queue=False,  # a market order fills at the quote it was sent on (the bar's open)
        bar_execution=False,
    )
    engine.add_instrument(
        CurrencyPair(
            INSTRUMENT_ID,
            Symbol("COINX/USDX"),
            COINX,
            USDX,
            PRECISION,
            PRECISION,
            Price(10.0**-PRECISION, PRECISION),
            Quantity(10.0**-PRECISION, PRECISION),
            0,
            0,
        )
    )
    return engine


def run(rule: Callable, params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Run a reference rule on Nautilus. Same arguments, columns and ``attrs`` as the rule itself
    (``trade_returns``, ``n_trades`` and the fill log ``trades``), plus ``attrs["fills_usd"]``: each fill's
    traded notional and commission in USD as Nautilus booked them."""
    decide, costs = decider(rule, params, bars, costs)
    opens = bars["open"].to_numpy(dtype=float).tolist()
    closes = bars["close"].to_numpy(dtype=float).tolist()
    index = [int(ts) for ts in bars.index.as_unit("ns").asi8]
    engine = _engine(costs)
    strategy = _RuleStrategy(StrategyConfig()).setup(opens, closes, index, decide, costs)
    try:
        engine.add_data(_quotes(opens, closes, index))
        engine.add_strategy(strategy)
        engine.run()
    finally:
        engine.dispose()
    if strategy.error is not None:
        raise strategy.error
    if strategy.problems:
        raise NautilusRunError("; ".join(strategy.problems))
    if strategy.t_close != len(closes) - 1:
        raise NautilusRunError(f"the engine stopped at bar {strategy.t_close} of {len(closes) - 1}")
    return _result(bars, strategy, costs)


def _result(bars: pd.DataFrame, s: _RuleStrategy, costs: Costs) -> pd.DataFrame:
    n = len(s.closes)
    value = [s.cash_close[t] + s.coin_close[t] * s.closes[t] for t in range(n)]
    ret, pos, turnover, cost = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    for t in range(1, n):
        ret[t] = value[t] / value[t - 1] - 1.0
        pos[t] = s.coin_close[t] * s.closes[t] / value[t]
    by_bar = {s.order_bar[oid]: fills for oid, fills in s.fills.items()}
    if set(by_bar) != set(s.pre):
        raise NautilusRunError(f"orders sent on bars {sorted(s.pre)} but filled on bars {sorted(by_bar)}")
    log, usd = [], []
    trade_returns, entry_value = [], None
    for t in range(1, n):
        if t not in s.pre:
            continue
        fills = by_bar[t]
        if len(fills) != 1:
            raise NautilusRunError(f"the order on bar {t} filled in {len(fills)} parts, expected 1")
        qty, px, commission = fills[0]
        _, coin_before, v_open, drifted, intended, fee = s.pre[t]
        if not math.isclose(commission, fee, rel_tol=0.0, abs_tol=1e-9):
            raise NautilusRunError(f"bar {t}: Nautilus charged {commission} USD, the cost model {fee} USD")
        o = s.opens[t]
        v_after = s.cash_close[t] + s.coin_close[t] * o  # the book right after the fill, at the open
        weight = s.coin_close[t] * o / v_after
        turnover[t] = abs(weight - drifted)
        cost[t] = commission / v_open
        log.append((t, o, drifted, weight, turnover[t], cost[t]))
        usd.append((bars.index[t], qty * px, commission))
        if coin_before == 0.0:
            entry_value = value[t - 1]
        if s.coin_close[t] == 0.0:
            trade_returns.append(value[t] / entry_value - 1.0)
            entry_value = None
    if entry_value is not None:  # still open: marked to market at the last close
        trade_returns.append(value[-1] / entry_value - 1.0)
    result = pd.DataFrame(
        {"ret": ret, "position": pos, "turnover": turnover, "cost": cost}, index=bars.index, dtype=float
    )
    result.attrs["trade_returns"] = np.asarray(trade_returns, dtype=float)
    result.attrs["n_trades"] = len(log)
    result.attrs["trades"] = _fills_frame(bars.index, log)
    result.attrs["fills_usd"] = pd.DataFrame(usd, columns=["ts", "notional_usd", "commission_usd"])
    return result


def wrap(rule: Callable) -> Callable[..., pd.DataFrame]:
    """A ``BacktestFn`` ``fn(params, bars, costs=None)`` that runs ``rule`` on Nautilus.

    It is a ``functools.partial`` of :func:`run`, so it pickles (for a module-level rule) and a parallel search
    (``lab.search.study``, spawned worker processes) can use it."""
    fn = functools.partial(run, rule)
    fn.__name__ = f"nautilus_{getattr(rule, '__name__', 'rule')}"
    return fn
