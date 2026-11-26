"""The multi-asset rebalancer (``lab/runner/portfolio.py``) on a NautilusTrader v2 ``BacktestEngine`` (milestone 3).

**What Nautilus does here.** Every run builds one engine, one simulated venue (a cash account, spot only: no
borrowing, no leverage), two instruments (BTCX/USDX and ETHX/USDX, one cash currency) and one strategy, runs it and
disposes of it (AGENTS.md "Running many simulations", rule 1). Nautilus holds the book: the USD cash and both
coins' units are Nautilus account balances, every leg is a Nautilus market order, every fill and its commission
come from the Nautilus matching engine and :class:`lab.costs.fees.DexFeeModel`. The result is read off the
balances.

**The rules are portfolio.py's rules.** :func:`run` calls a rule built on ``portfolio._simulate``
(``portfolio.rebalance``, ``portfolio.random_rebalance``, ``holdmix.hold_mix``, ``trend.trend_backtest``,
``trend.run_states``, ...) with its module's ``_simulate`` replaced, for the length of the call, by :func:`simulate`,
which runs the rule's own ``decide`` function on Nautilus. So the rule validates its params and panel as usual
(``ValueError`` before any engine is built), both engines decide with one piece of code (the owner's option B,
docs/app/technical.md "Strategy settings"), and whatever the rule does with the result afterwards (holdmix's
reasons and waits, trend's order hash, a stop variant's reruns) runs on the Nautilus result. The swap holds a
lock, so threads run one at a time; parallel searches use processes (``wrap``).

**Execution model (portfolio.py's, hard rule 4).** Each bar is fed as quotes per coin: its opens, 1 ns after the
previous close, the opens again 1 ns later, and its closes at the bar's close time. When both closes of bar t are
in, the rule decides a target vector from the weights at that close (to the book's 12 decimals, as in
``nautilus.py``). At the first opens of bar t+1 the strategy sizes every coin from the account: V_open = cash + sum
units x open, each leg's intended notional usd_a = |w_a - drifted_a| x V_open and its fee ``fee_usd(costs, usd_a)``
(the reference's leg cost), F = sum of fees; every coin is cut to w_a x (V_open - F) / open_a units, so the book
holds exactly the targets after the fill (portfolio.py shares the cost pro rata). The sells go at the first opens
(rounded up to 1e-12 units, capped at the exact balance, #62; in descending order of what each adds to the cash,
since a sell can pay more fee than it raises), the buys at the second (fills land only after a handler returns),
each capped at the cash left in fixed point (``nautilus._affordable``). A fill whose fees are >= the book raises
portfolio.py's own message. A decision at the last close is made (the rule may record it) but never sent.

**Documented differences from portfolio.py** (TESTING.md #65):
- a leg of at most ``MIN_LEG`` (1e-9 of the book) is round-off, never a trade: a fill whose legs are all round-off
  is not sent (portfolio.py trades any leg > 0 and pays gas for it, #36, #61), and a round-off leg inside a real
  fill is a **re-cut**: a zero-commission order (``fees.RECUT_TAG``) that moves the coin by its share of the fees,
  as portfolio.py's pro-rata cost does without a swap. A target of round-off size (e.g. 1e-126) is never bought;
- a book all in one coin keeps cash below one unit step that a buy cannot spend, so with band 0 the rule can see
  0.999999999999 and order; that order fills nothing (``attrs["orders"]`` lists it, the book is unchanged);
- the rule sees each weight to 12 decimals; a leg below one 1e-12-unit step cannot be sent and pays nothing.
"""

from __future__ import annotations

import functools
import math
import threading
from collections.abc import Callable
from decimal import ROUND_UP, Decimal

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
    QuoteTick,
    Symbol,
    TraderId,
)
from nautilus_trader.trading import Strategy

from lab.costs.fees import RECUT_TAG, DexFeeModel, fee_usd, intended_tag
from lab.runner import portfolio
from lab.runner.nautilus import (
    _BOOK_SIZE,
    _STEP,
    MIN_LEG,
    PRECISION,
    TOL,
    USDX,
    VENUE,
    NautilusRunError,
    _affordable,
    _units,
)
from lab.runner.portfolio import ASSETS, WEIGHT_COLUMNS, _fills_frame
from lab.runner.reference import Costs

__all__ = ["MIN_LEG", "PRECISION", "TOL", "NautilusRunError", "run", "simulate", "wrap"]

COINS = tuple(Currency(f"{a}X", PRECISION, 0, f"lab {a}", CurrencyType.CRYPTO) for a in ASSETS)
INSTRUMENT_IDS = tuple(InstrumentId(Symbol(f"{a}X/USDX"), VENUE) for a in ASSETS)
_M = len(ASSETS)


def _up(x: Decimal) -> Decimal:
    """A non-negative amount rounded UP to the instrument's precision."""
    return max(x, Decimal(0)).quantize(_STEP, rounding=ROUND_UP)


class _Strategy(Strategy):
    def setup(self, opens, closes, index, ts_index, decide, costs: Costs) -> _Strategy:
        self.opens, self.closes, self.index, self.ts_index = opens, closes, index, ts_index
        self.decide, self.costs = decide, costs
        n = len(index)
        self.cash_close = [0.0] * n
        self.units_close = [[0.0] * n for _ in range(_M)]
        self.pre = {}  # bar t -> (v_open, drifted, legs: {asset: (intended_usd, fee)}) of a fill at its open
        self.fills = {}  # client order id -> list of (qty, px, commission)
        self.order_leg = {}  # client order id -> (bar, asset, a re-cut)
        self.orders: list[int] = []
        self.problems: list[str] = []
        self.error: BaseException | None = None
        self.target: tuple | None = None
        self.t_close = -1
        self.seen = 0
        self.buys: list[tuple[int, float, bool]] = []  # (asset, units to buy, a re-cut) sized at the opens
        return self

    def on_start(self) -> None:
        for iid in INSTRUMENT_IDS:
            self.subscribe_quotes(iid)

    def _account(self):
        return self.portfolio.account(VENUE)

    def _balances(self) -> tuple[float, list[float]]:
        acc = self._account()
        return float(acc.balance_total(USDX)), [float(acc.balance_total(c)) for c in COINS]

    def on_quote(self, quote: QuoteTick) -> None:
        if self.error is not None:
            return
        self.seen += 1
        if self.seen < _M:  # act once every coin's quote of this phase is in
            return
        self.seen = 0
        t = self.t_close + 1
        try:
            if quote.ts_event == self.index[t]:
                self._on_close(t)
            elif quote.ts_event == self.index[t - 1] + 1:
                self._on_open(t)
            else:
                self._on_buys(t)
        except Exception as exc:  # re-raised by simulate() as itself, not as an engine error
            self.error = exc

    def _send(self, t: int, a: int, side, qty, recut: bool) -> bool:
        if float(qty) == 0.0:  # below one 1e-12-unit step: Nautilus cannot trade it, so it pays nothing
            if not recut:
                del self.pre[t][2][a]
            return False
        tag = RECUT_TAG if recut else intended_tag(self.pre[t][2][a][0])
        order = self.order_factory.market(INSTRUMENT_IDS[a], side, qty, tags=[tag])
        self.order_leg[order.client_order_id] = (t, a, recut)
        self.submit_order(order)
        return True

    def _on_open(self, t: int) -> None:
        """Size every coin from the book at the opens and send the sells. Fills (and the cash they free) land
        after this handler returns, so the buys go at the second open quote (:meth:`_on_buys`)."""
        self.buys = []
        target = self.target
        if target is None:
            return
        cash, units = self._balances()
        o = [self.opens[a][t] for a in range(_M)]
        v_open = cash
        for a in range(_M):
            v_open += units[a] * o[a]
        drifted = [units[a] * o[a] / v_open for a in range(_M)]
        traded = [abs(target[a] - drifted[a]) for a in range(_M)]
        if max(traded) <= MIN_LEG:
            return
        legs = {}
        for a in range(_M):
            if traded[a] > MIN_LEG:
                usd = traded[a] * v_open
                legs[a] = (usd, fee_usd(self.costs, usd))
        fees = sum(fee for _, fee in legs.values())
        k = fees / v_open
        if k >= 1.0:
            raise ValueError(
                f"costs of the fill on {self.ts_index[t]} are {k:.1%} of a portfolio worth {v_open:.4g} USD: "
                "it cannot pay them (raise capital_usd or check the cost model)"
            )
        self.pre[t] = (v_open, drifted, legs, target)
        v_after = v_open - fees
        acc = self._account()
        sells = []
        for a in range(_M):
            recut = a not in legs  # at its target to round-off: moved by its share of the fees, at no cost
            want = target[a] * v_after / o[a]  # units that hold exactly the target after every leg's fee
            if target[a] == 0.0 or want < units[a]:
                # Sells are rounded UP and capped at the exact balance (#62): the fees come out of the cash, and
                # with no cash target the sells must fund them to the last step (#65 (c)).
                held = Decimal(str(acc.balance_total(COINS[a]).as_decimal()))
                qty = held if target[a] == 0.0 else min(_up(Decimal(repr(units[a] - want))), held)
                fee = 0.0 if recut else legs[a][1]
                sells.append((float(qty) * o[a] - fee, a, _units(qty), recut))
            else:
                self.buys.append((a, want - units[a], recut))
        # A sell can pay more fee than it raises; in order of what each adds to the cash, every running total stays
        # at or above the lower of the cash before (>= 0) and after all of them (>= the buys and cash target, >= 0).
        for _, a, qty, recut in sorted(sells, key=lambda x: -x[0]):
            self._send(t, a, OrderSide.SELL, qty, recut)

    def _on_buys(self, t: int) -> None:
        """The buys, at the second quote of the opens, after the sells have filled: each capped at what the cash
        left can pay in fixed point (the price and fee as Nautilus rounds them, nautilus._affordable)."""
        if t not in self.pre:
            return
        legs = self.pre[t][2]
        cash = Decimal(str(self._account().balance_total(USDX).as_decimal()))
        for a, more, recut in self.buys:
            o, fee = self.opens[a][t], 0.0 if recut else legs[a][1]
            qty = _units(min(Decimal(repr(more)), _affordable(Money(cash, USDX), fee, o)))
            if self._send(t, a, OrderSide.BUY, qty, recut):
                cash -= Decimal(str(qty)) * Decimal(str(Price(o, PRECISION))) + Decimal(
                    str(Money(fee, USDX).as_decimal())
                )
        self.buys = []
        if not legs:
            del self.pre[t]

    def _on_close(self, t: int) -> None:
        self.t_close = t
        cash, units = self._balances()
        self.cash_close[t] = cash
        value = cash
        for a in range(_M):
            self.units_close[a][t] = units[a]
            value += units[a] * self.closes[a][t]
        w = tuple(round(units[a] * self.closes[a][t] / value, PRECISION) for a in range(_M))
        self.target = self.decide(t, w)
        if self.target is not None and t < len(self.index) - 1:
            self.orders.append(t)

    def on_order_filled(self, event) -> None:
        self.fills.setdefault(event.client_order_id, []).append(
            (float(event.last_qty), float(event.last_px), float(event.commission))
        )

    def on_order_denied(self, event) -> None:
        self.problems.append(f"order denied: {event}")

    def on_order_rejected(self, event) -> None:
        self.problems.append(f"order rejected: {event}")


def _quotes(opens, closes, index) -> list[QuoteTick]:
    ticks = []
    for t, ts in enumerate(index):
        for a, iid in enumerate(INSTRUMENT_IDS):
            if t > 0:  # bar 0's open can't fill anything (no decision exists yet)
                px = Price(opens[a][t], PRECISION)
                ticks.append(
                    QuoteTick(iid, px, px, _BOOK_SIZE, _BOOK_SIZE, index[t - 1] + 1, index[t - 1] + 1)
                )
        for a, iid in enumerate(INSTRUMENT_IDS):
            if t > 0:  # the opens again, 1 ns later: the buys go here, once the sells have filled
                px = Price(opens[a][t], PRECISION)
                ticks.append(
                    QuoteTick(iid, px, px, _BOOK_SIZE, _BOOK_SIZE, index[t - 1] + 2, index[t - 1] + 2)
                )
        for a, iid in enumerate(INSTRUMENT_IDS):
            px = Price(closes[a][t], PRECISION)
            ticks.append(QuoteTick(iid, px, px, _BOOK_SIZE, _BOOK_SIZE, ts, ts))
    return ticks


def _engine(costs: Costs) -> BacktestEngine:
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId("LAB-002"),
            logging=LoggerConfig(stdout_level=LogLevel.ERROR, bypass_logging=True),
        )
    )
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.CASH,
        [Money(costs.capital_usd, USDX), *(Money(0, c) for c in COINS)],
        fee_model=DexFeeModel(costs, USDX),
        use_message_queue=False,  # a market order fills at the quote it was sent on (the bar's open)
        bar_execution=False,
    )
    step_px, step_qty = Price(10.0**-PRECISION, PRECISION), _units(Decimal(1).scaleb(-PRECISION))
    for iid, coin in zip(INSTRUMENT_IDS, COINS, strict=True):
        engine.add_instrument(
            CurrencyPair(iid, iid.symbol, coin, USDX, PRECISION, PRECISION, step_px, step_qty, 0, 0)
        )
    return engine


def simulate(bars: pd.DataFrame, costs: Costs, decide) -> pd.DataFrame:
    """``portfolio._simulate(bars, costs, decide)`` on Nautilus: same columns and ``attrs`` (``trade_returns``,
    ``n_trades``, ``fills``, ``orders``, ``snapshot_id``), plus ``fills_usd``: each leg's traded notional and
    commission in USD as Nautilus booked them."""
    opens = [bars[(a, "open")].to_numpy(dtype=float).tolist() for a in ASSETS]
    closes = [bars[(a, "close")].to_numpy(dtype=float).tolist() for a in ASSETS]
    index = [int(ts) for ts in bars.index.as_unit("ns").asi8]
    engine = _engine(costs)
    s = _Strategy(StrategyConfig()).setup(opens, closes, index, bars.index, decide, costs)
    try:
        engine.add_data(_quotes(opens, closes, index))
        engine.add_strategy(s)
        engine.run()
    finally:
        engine.dispose()
    if s.error is not None:
        raise s.error
    if s.problems:
        raise NautilusRunError("; ".join(s.problems))
    if s.t_close != len(index) - 1:
        raise NautilusRunError(f"the engine stopped at bar {s.t_close} of {len(index) - 1}")
    return _result(bars, s)


def _result(bars: pd.DataFrame, s: _Strategy) -> pd.DataFrame:
    n = len(s.index)
    value = [s.cash_close[t] + sum(s.units_close[a][t] * s.closes[a][t] for a in range(_M)) for t in range(n)]
    ret, pos, turnover, cost = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    weights = [[0.0] * n for _ in range(_M)]
    for t in range(1, n):
        ret[t] = value[t] / value[t - 1] - 1.0
        for a in range(_M):
            weights[a][t] = s.units_close[a][t] * s.closes[a][t] / value[t]
        pos[t] = sum(weights[a][t] for a in range(_M))
    if set(s.fills) != set(s.order_leg):
        raise NautilusRunError(f"{len(s.order_leg)} orders sent but {len(s.fills)} filled")
    by_leg, recut = {}, 0.0
    for oid, fills in s.fills.items():
        t, a, is_recut = s.order_leg[oid]
        if len(fills) != 1:
            raise NautilusRunError(
                f"the {ASSETS[a]} order on bar {t} filled in {len(fills)} parts, expected 1"
            )
        if is_recut:
            recut += abs(fills[0][2])
        else:
            by_leg[(t, a)] = fills[0]
    if recut != 0.0:
        raise NautilusRunError(f"Nautilus charged {recut} USD for re-cuts, which are free")
    legs_log, usd_log, fill_open = [], [], []
    for t in sorted(s.pre):
        v_open, drifted, legs, target = s.pre[t]
        # nothing trades between the open and the close, so the close balances are the book right after the fill
        cash_after, units_after = s.cash_close[t], [s.units_close[a][t] for a in range(_M)]
        o = [s.opens[a][t] for a in range(_M)]
        v_after = cash_after + sum(units_after[a] * o[a] for a in range(_M))
        commission_total = 0.0
        for a in sorted(legs):
            usd, fee = legs[a]
            qty, px, commission = by_leg[(t, a)]
            if not math.isclose(commission, fee, rel_tol=0.0, abs_tol=1e-9):
                raise NautilusRunError(
                    f"bar {t}: Nautilus charged {commission} USD, the cost model {fee} USD"
                )
            commission_total += commission
            legs_log.append((t, a, drifted[a], target[a], usd, commission))
            usd_log.append((bars.index[t], ASSETS[a], qty * px, commission))
        turnover[t] = sum(abs(units_after[a] * o[a] / v_after - drifted[a]) for a in range(_M))
        cost[t] = commission_total / v_open
        fill_open.append(v_open)
    ends = fill_open[1:] + [value[-1]] if fill_open else []
    result = pd.DataFrame(
        {
            "ret": ret,
            "position": pos,
            "turnover": turnover,
            "cost": cost,
            **{col: weights[a] for a, col in enumerate(WEIGHT_COLUMNS)},
        },
        index=bars.index,
        dtype=float,
    )
    result.attrs["trade_returns"] = np.asarray(
        [end / start - 1.0 for start, end in zip(fill_open, ends, strict=True)], dtype=float
    )
    result.attrs["n_trades"] = len(fill_open)
    result.attrs["fills"] = _fills_frame(bars, s.opens, legs_log)
    result.attrs["orders"] = np.asarray(s.orders, dtype=np.int64)
    result.attrs["snapshot_id"] = bars.attrs["snapshot_id"]
    cols = list(zip(*usd_log, strict=True)) or [[]] * 4
    result.attrs["fills_usd"] = pd.DataFrame(
        {
            "ts": pd.DatetimeIndex(cols[0], tz="UTC") if usd_log else bars.index[:0],
            "asset": np.asarray(cols[1], dtype=object),
            "notional_usd": np.asarray(cols[2], dtype=float),
            "commission_usd": np.asarray(cols[3], dtype=float),
        }
    )
    return result


# ----------------------------------------------------------------------------------------------- running

_SWAP_LOCK = threading.RLock()


_ENGINE = portfolio._simulate  # the reference engine, put back after every run


def _module_globals(rule: Callable) -> dict:
    fn = rule
    while isinstance(fn, functools.partial):
        fn = fn.func
    space = getattr(fn, "__globals__", None)
    if space is None or space.get("_simulate") is not _ENGINE:
        raise ValueError(
            f"{getattr(fn, '__name__', fn)!r} is not a portfolio rule (its module has no portfolio._simulate)"
        )
    return space


def run(rule: Callable, *args, **kwargs) -> pd.DataFrame:
    """``rule(*args, **kwargs)`` with every ``portfolio._simulate`` call it makes run on Nautilus (:func:`simulate`).
    The rule's module gets its own ``_simulate`` back afterwards, also when the rule raises. ``ValueError`` for a
    function that is not a portfolio rule (its module does not use ``portfolio._simulate``, or it never reached it)."""
    space = _module_globals(rule)
    calls = []

    def on_nautilus(bars, costs, decide):
        calls.append(1)
        return simulate(bars, costs, decide)

    with _SWAP_LOCK:
        space["_simulate"] = on_nautilus
        try:
            result = rule(*args, **kwargs)
        finally:
            space["_simulate"] = _ENGINE
    if not calls:
        raise ValueError(
            f"{getattr(rule, '__name__', rule)!r} is not a portfolio rule (it never reached the engine)"
        )
    return result


def wrap(rule: Callable) -> Callable[..., pd.DataFrame]:
    """A ``BacktestFn`` ``fn(params, bars, costs=None)`` (or whatever ``rule`` takes) that runs ``rule`` on
    Nautilus. A ``functools.partial`` of :func:`run`, so it pickles for a module-level rule (a parallel search)."""
    fn = functools.partial(run, rule)
    fn.__name__ = f"nautilus_{getattr(rule, '__name__', 'rule')}"
    return fn
