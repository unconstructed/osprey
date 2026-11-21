"""The "hold this mix" tool: its rule, its per-run metrics and the hold-mix-cap study's decision rules.

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the
reference rebalancer, not NautilusTrader (AGENTS.md hard rule 3). ``research/hold-mix-cap/PLAN.md`` is the
contract; section numbers below are that file's. No existing file is changed: :func:`hold_mix` hands its decisions
to ``portfolio._simulate`` with a ``decide`` callback, exactly as ``portfolio.rebalance`` does.

The rule (sections 4.1-4.3)
---------------------------
The customer picks targets T_BTC = s*f and T_ETH = s*(1 - f) (cash 1 - s, in USDC; :func:`mix_targets`), a drift
band b RELATIVE to each coin's target, and a cap of N rebalances a month, kept as a wait of W = ceil(30 / N) days
(:func:`wait_days`; no cap is W = 1). Once a day, at the close, with w = the weights at that close (drifted by
prices since the last fill), the first matching step decides:

1. close 0 (all cash): buy the targets, reason ``first``. Not a rebalance: not counted, and it does not start the
   wait (amendment A1; ``first_buy_waits=True`` is the other reading, a description only, where it does).
2. a Steady limit is breached (``portfolio._breach_test`` at the limits themselves, round-off 1e-9): trade back to
   the targets, reason ``limit``, **even inside the wait**. Counted; it restarts the wait.
3. the wait runs (some counted order was sent less than W calendar days ago, by close time): no order. A band
   break or a due reset held here is listed in ``held``.
4. BTC or ETH, among the coins with a target > 0, has ``abs(w - T) > b * T`` (strict): reason ``band``.
5. a reset is set and R days have passed since the last order of ANY kind (the first buy included): ``reset``.
6. otherwise no order.

Every order is the full target vector and fills at the next open (hard rule 4); the decision at the last close is
never sent. One order per close at most, so one rebalance counts once however many legs it swaps.

Result: ``portfolio._simulate``'s DataFrame and attrs (``ret``, ``position``, ``turnover``, ``cost``, ``w_BTC``,
``w_ETH``; ``n_trades``, ``trade_returns``, ``fills``, ``orders``, ``snapshot_id``), plus

- ``reasons``: one reason per entry of ``orders`` (object array of ``first``/``limit``/``band``/``reset``);
- ``in_wait``: one bool per order, True for a limit order sent while a wait was running;
- ``held``: the closes in 1 .. n-2 where the wait held a band break or a due reset (int64; a hold at the last
  close, whose decision is never sent, is not listed).

The decisions read only the weights, which costs and the wallet size never change (section 4.6): the engine
re-cuts the book to the targets after a fill and between fills the weights drift by prices only.

Per-run metrics (section 8)
---------------------------
:func:`path_metrics` (closeness and counts), :func:`trade_sizes` (legs) and :func:`money_metrics` (fees, gas,
return, Sharpe, falls with their dates) are computed from the engine's result and fill log, never re-simulated.
:func:`check_path` and the fee check inside :func:`money_metrics` raise :class:`ConsistencyError` (stop rule 8)
when a result breaks the rule. :func:`path_hash` hashes what must not depend on costs.

The runs table (the decision rules' input; ``run.py`` writes it)
---------------------------------------------------------------
One row per run with the key columns of :data:`RUN_KEYS`: ``source`` ("KRAKEN"/"BINANCE"), ``scope``
("rolling"/"full"), ``window`` (k; -1 for a full run), ``comparator`` ("grid"/"limit-only"), ``reading``
("lab"/"other", the first-buy reading), ``s``, ``f``, ``b`` (NaN for limit-only), ``cap`` (:func:`cap_label`:
"none", "8", ..., "0.25"; "none" for limit-only), ``R`` (reset days, NaN = none), ``V`` (wallet USD), ``cost``
("1x"/"2x") and ``status`` ("ok"/"failed"), plus the metric columns named by the functions above (a failed run has
NaN metrics). ``limit_only_bands`` (limit-only's band metrics) has the same keys with ``b`` set to each grid band.
:func:`pool` and :func:`limit_only_pool` select one source's decision pool. Rules B, A, C and D are
:func:`cap_for_band`, :func:`default_band`, :func:`upper_limit` and :func:`robust`; :func:`decide_source` runs
B, A and C for one source; :func:`descriptions` and :func:`falls_tables` are section 9's descriptions and section
10's falls. Every threshold is inclusive, medians and percentiles are ``numpy.median`` and ``numpy.percentile``
(linear), and a pool holding a failed run gives ``MISSING`` (rule E) until :func:`drop_failed_pairs` drops it.
:func:`boom_plan` and :func:`boom_compare` are the boom-year addendum (amendment A5): which windows each removal of
a year keeps, and whether the recomputed rule D keeps the headline's values.
"""

from __future__ import annotations

import hashlib
import math
import numbers
from collections.abc import Callable, Iterable, Mapping, Sequence
from fractions import Fraction

import numpy as np
import pandas as pd

from lab.runner.portfolio import (
    WEIGHT_COLUMNS,
    _breach_test,
    _prepare,
    _simulate,
    _targets,
    check_targets,
    validate_panel,
)
from lab.runner.reference import _REQUIRED, Costs, _check_params, _get, _param_float, _param_int, _real
from lab.validation import stats
from lab.validation.montecarlo import max_drawdown

__all__ = [
    "BANDS",
    "BOOKS",
    "CAPS",
    "CAP_LABELS",
    "FINITE_CAPS",
    "HEADROOM",
    "MIXES",
    "MONTH_DAYS",
    "ConsistencyError",
    "WindowSliceError",
    "app_default",
    "acceptable",
    "bar_years",
    "best_years",
    "boom_compare",
    "boom_plan",
    "boom_removals",
    "cap_for_band",
    "cap_label",
    "check_grid",
    "check_path",
    "decide_source",
    "default_band",
    "descriptions",
    "drop_failed_pairs",
    "extra_out",
    "falls_tables",
    "feasible_mixes",
    "full_window",
    "hold_mix",
    "limit_only_pool",
    "mix_targets",
    "money_metrics",
    "outcome_label",
    "overlaps",
    "path_hash",
    "path_metrics",
    "pool",
    "robust",
    "rolling_windows",
    "trade_sizes",
    "upper_limit",
    "wait_days",
    "window_slice",
    "windows_without",
    "year_returns",
]

# ------------------------------------------------------------------------------------------------ pinned values

HEADROOM = 0.02  # the lab's 2-point margin (rebalance-steady A2)
MONTH_DAYS = 30  # the cap's month
YEAR_DAYS = 365
DAY_US = 86_400_000_000  # one day in microseconds (the panel's index unit)
CAPS = (None, 8, 4, 2, 1, 0.5, 0.25)  # None = no cap
BANDS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.50)
S_VALUES = (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.78)
F_VALUES = (0.0, 0.25, 0.50, 0.75, 1.0)
MIXES = (
    *((s, f) for s in (0.20, 0.30, 0.40, 0.50) for f in F_VALUES),
    *((s, f) for s in (0.60, 0.70) for f in (0.25, 0.50, 0.75)),
    (0.78, 0.50),
)
BOOKS = (500.0, 5000.0, 50000.0)
REF_BOOK = 5000.0  # closeness numbers and rebalance counts come from the 5,000 USD 1x runs
COST_LABELS = ("1x", "2x")
RESET_DAYS = 365
REASONS = ("first", "limit", "band", "reset")
LIMIT_ONLY_BAND = 1000.0  # b * T >= 50 for every grid target: the band never fires

# Decision thresholds (section 9), fixed before any result
EXTRA_OUT_MEDIAN = 7.0
EXTRA_OUT_P90 = 30.0
RATE_MAX = 1.0
FEE_MAX = 0.25
CLOSE_SHARE = 0.90
VALUE_FACTOR = 2.0

# Outcome words
MISSING = "MISSING"
MORE_THAN_8 = "more than 8"
NO_BAND = "none"
NO_BAND_FLAG = "NO BAND MET THE CONDITIONS"
NO_EVIDENCE = "NO EVIDENCE"
ABOVE_8 = "ABOVE 8"
EVIDENCE = "EVIDENCE FOR A LIMIT"
SUPPORTED = "SUPPORTED"
WEAK = "WEAK"
ROBUST = "ROBUST"
NOT_ROBUST = "NOT ROBUST"
OK = "ok"
LABEL = "SCOUTING, placeholder costs, train years 2017-2022, reference engine"
STATUS = "SCOUTING evidence for the owner; sets no limit"
FALLS_NOTE = (
    "SCOUTING, hypothetical: simulated on past prices, 2017-2022 train years (the window or the full span is named), "
    "in-sample, reference engine, placeholder costs. Not the worst fall the app shows, and not a drawdown budget."
)

# Windows (sections 3 and 6), from the calendar and DATA.md, never from the data
SOURCES = ("KRAKEN", "BINANCE")
FIRST_CLOSE = {
    "KRAKEN": pd.Timestamp("2017-01-02", tz="UTC"),
    "BINANCE": pd.Timestamp("2017-08-18", tz="UTC"),
}
LAST_CLOSE = pd.Timestamp("2023-01-01", tz="UTC")
MISSING_CLOSES = {"KRAKEN": (pd.Timestamp("2018-01-13", tz="UTC"),), "BINANCE": ()}
N_WINDOWS = 60
NON_OVERLAPPING = (0, 12, 24, 36, 48)
# The other readings of the Steady limits (section 9): 60% capping cash needs cash <= 0.58 (s >= 0.42); 60% capping
# the two coins together needs s <= 0.58 (with h = 0.02)
CASH_READING_MIN_S = 0.42
TOGETHER_READING_MAX_S = 0.58

CAP_LABELS = ("none", "8", "4", "2", "1", "0.5", "0.25")
FINITE_CAPS = ("0.25", "0.5", "1", "2", "4", "8")  # tightest to loosest
RUN_KEYS = ("source", "scope", "window", "comparator", "reading", "s", "f", "b", "cap", "R", "V", "cost")
PAIR = ("s", "f", "window")


class ConsistencyError(ValueError):
    """A result that breaks the rule or the accounting (PLAN.md stop rule 8): the run must stop."""


class WindowSliceError(ValueError):
    """A slice whose closes are not exactly the calendar's (PLAN.md stop rule 5 and section 6)."""


# --------------------------------------------------------------------------------------------- the cap and mix


def _cap(cap):
    if isinstance(cap, bool) or not isinstance(cap, numbers.Real) or not (math.isfinite(cap) and cap > 0):
        raise ValueError(f"cap must be None (no cap) or a number of rebalances a month > 0, got {cap!r}")
    return cap


def wait_days(cap) -> int:
    """The minimum wait in days for a cap of ``cap`` rebalances a month: None (no cap) -> 1, else ceil(30 / N) in
    exact decimal arithmetic (``Fraction(30) / Fraction(str(N))``, so 30 / 0.3 gives exactly 100)."""
    if cap is None:
        return 1
    return math.ceil(Fraction(MONTH_DAYS) / Fraction(str(_cap(cap))))


def cap_label(cap) -> str:
    """The runs table's name of a cap: ``"none"`` for None, else the number in ``g`` format (8 -> "8")."""
    return "none" if cap is None else format(float(_cap(cap)), "g")


def mix_targets(s: float, f: float) -> tuple[float, float]:
    """(T_BTC, T_ETH) = (s * f, s * (1 - f)) for a crypto share s and a BTC share f of the crypto, each in [0, 1]."""
    s = _real(s, "s", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    f = _real(f, "f", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    return (s * f, s * (1.0 - f))


def feasible_mixes(min_cash, max_coin, headroom: float = HEADROOM) -> list[tuple[float, float]]:
    """The (s, f) pairs of the grid's crypto and BTC shares whose targets ``portfolio.check_targets`` accepts."""
    out = []
    for s in S_VALUES:
        for f in F_VALUES:
            w_btc, w_eth = mix_targets(s, f)
            try:
                check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=headroom)
            except ValueError:
                continue
            out.append((s, f))
    return out


def check_grid(min_cash, max_coin, headroom: float = HEADROOM) -> None:
    """``ValueError`` naming every mix of :data:`MIXES` that ``check_targets`` refuses under these limits (run.py
    checks the grid this way before loading any bar)."""
    refused = []
    for s, f in MIXES:
        w_btc, w_eth = mix_targets(s, f)
        try:
            check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=headroom)
        except ValueError:
            refused.append((s, f))
    if refused:
        raise ValueError(
            f"the grid's mixes {refused} break min_cash = {min_cash!r}, max_coin = {max_coin!r} with headroom "
            f"{headroom!r}: amend the grid before any run"
        )


# ------------------------------------------------------------------------------------------------ the rule

_HOLD_MIX_PARAMS = frozenset(
    {
        "w_btc",
        "w_eth",
        "band",
        "wait_days",
        "min_cash",
        "max_coin",
        "headroom",
        "reset_days",
        "first_buy_waits",
    }
)


def _required_limit(p: Mapping, key: str) -> float | None:
    if _get(p, key, _REQUIRED) is None:
        return None
    return _param_float(p, key, low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)


def _hold_params(params) -> dict:
    p = _check_params("hold_mix", params, _HOLD_MIX_PARAMS)
    targets = _targets(p, "hold_mix")
    min_cash, max_coin = _required_limit(p, "min_cash"), _required_limit(p, "max_coin")
    headroom = _param_float(p, "headroom", low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    if headroom > 0.0 and min_cash is None and max_coin is None:
        raise ValueError(f"hold_mix: headroom = {headroom!r} needs a limit (min_cash or max_coin)")
    if _breach_test(min_cash, max_coin, headroom)(targets):
        raise ValueError(
            f"hold_mix: the targets w_btc = {targets[0]!r}, w_eth = {targets[1]!r} break the limits "
            f"min_cash = {min_cash!r}, max_coin = {max_coin!r}, headroom = {headroom!r}"
        )
    first_buy_waits = p.get("first_buy_waits", False)
    if not isinstance(first_buy_waits, bool):
        raise ValueError(f"first_buy_waits must be True or False, got {first_buy_waits!r}")
    return {
        "targets": targets,
        "min_cash": min_cash,
        "max_coin": max_coin,
        "band": _param_float(p, "band", low=0.0, low_inclusive=True),
        "wait": _param_int(p, "wait_days"),
        "reset": None if p.get("reset_days") is None else _param_int(p, "reset_days"),
        "first_buy_waits": first_buy_waits,
    }


def hold_mix(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """The "hold this mix" rule (module docstring) on a BTC + ETH panel, through ``portfolio._simulate``.

    params (unknown keys, missing required keys and bad values raise ``ValueError``):

    - ``w_btc``, ``w_eth`` (required, each in [0, 1], sum <= 1): the targets (:func:`mix_targets`).
    - ``band`` (required, finite >= 0): the RELATIVE band b; a coin with target T > 0 is out of band when
      ``abs(w - T) > b * T``. A coin with target 0 is never out of band.
    - ``wait_days`` (required, int >= 1): W, the minimum wait in calendar days (:func:`wait_days`), counted from the
      close of the last counted order (limit, band or reset) by close time, not rows.
    - ``min_cash``, ``max_coin`` (required keys; a fraction in [0, 1], or None = off, for tests only): the Steady
      limits as ``portfolio.risk_limits("steady")`` reads them (never typed).
    - ``headroom`` (required, in [0, 1]; > 0 needs a limit): the targets must stay this far inside every set limit,
      as ``portfolio.check_targets`` checks them. Breaches are judged at the limits themselves.
    - ``reset_days`` (None or int >= 1; default None): the optional reset R, counted from the last order of any kind.
    - ``first_buy_waits`` (bool, default False = the lab's reading, A1; True only for the A1 description).

    ``costs=None`` reads ``config/costs.yaml``. Every order fills at the next open; see the module docstring for
    the result's extra attrs ``reasons``, ``in_wait`` and ``held``.
    """
    p = _hold_params(params)
    costs = _prepare(bars, costs)
    targets = p["targets"]
    times = bars.index.asi8.tolist()  # UTC microseconds (validate_panel pins the unit)
    last = len(times) - 1
    wait_us = p["wait"] * DAY_US
    reset_us = None if p["reset"] is None else p["reset"] * DAY_US
    coins = [(a, target, p["band"] * target) for a, target in enumerate(targets) if target > 0.0]
    breached = _breach_test(p["min_cash"], p["max_coin"])
    first_buy_waits = p["first_buy_waits"]
    reason_at: dict[int, str] = {}
    in_wait_at: dict[int, bool] = {}
    held: list[int] = []
    clock: dict[str, int | None] = {"any": None, "wait": None}

    def decide(t: int, w: tuple[float, ...]) -> tuple[float, ...] | None:
        now = times[t]
        waiting = clock["wait"] is not None and now - clock["wait"] < wait_us
        if t == 0:
            reason = "first"
        elif breached(w):
            reason = "limit"
        elif any(abs(w[a] - target) > limit for a, target, limit in coins):
            reason = "band"
        elif reset_us is not None and now - clock["any"] >= reset_us:
            reason = "reset"
        else:
            return None
        if waiting and reason != "limit":
            if t < last:
                held.append(t)
            return None
        reason_at[t] = reason
        in_wait_at[t] = waiting
        clock["any"] = now
        if reason != "first" or first_buy_waits:
            clock["wait"] = now
        return targets

    result = _simulate(bars, costs, decide)
    orders = result.attrs["orders"].tolist()
    result.attrs["reasons"] = np.asarray([reason_at[t] for t in orders], dtype=object)
    result.attrs["in_wait"] = np.asarray([in_wait_at[t] for t in orders], dtype=bool)
    result.attrs["held"] = np.asarray(held, dtype=np.int64)
    return result


# ------------------------------------------------------------------------------------------- checks and metrics


def _count(value, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def _days(us) -> float:
    return us / DAY_US


def _span_days(times: np.ndarray) -> float:
    return _days(int(times[-1] - times[0]))


def _most_in(times: np.ndarray, days: int) -> int:
    """The largest number of the (sorted) ``times`` in any stretch [t_i, t_i + days) starting at one of them."""
    if not len(times):
        return 0
    ends = np.searchsorted(times, times + days * DAY_US, side="left")
    return int((ends - np.arange(len(times))).max())


def check_path(result: pd.DataFrame, *, wait: int, first_buy_waits: bool = False) -> None:
    """Raise :class:`ConsistencyError` unless the result's orders follow the rule's counting (stop rule 8):

    - ``reasons`` and ``in_wait`` align with ``orders``; the one ``first`` order is at close 0; every reason is one
      of :data:`REASONS`; orders lie in closes 0 .. n-2;
    - counting only orders that are not limit orders, no stretch of 30 days holds more than ceil(30 / W) of them;
    - no order that is not a limit order comes less than W days after the previous counted order (with
      ``first_buy_waits``: the previous order of any kind), and ``in_wait`` is True exactly for the limit orders
      sent inside the wait;
    - ``held`` lies in closes 1 .. n-2, sorted, and holds no order close.
    """
    wait = _count(wait, "wait")
    attrs = result.attrs
    orders = np.asarray(attrs["orders"], dtype=np.int64)
    reasons = [str(r) for r in attrs["reasons"]]
    in_wait = [bool(x) for x in attrs["in_wait"]]
    held = np.asarray(attrs["held"], dtype=np.int64)
    n = len(result)
    if not len(orders) == len(reasons) == len(in_wait):
        raise ConsistencyError("reasons and in_wait flags are not aligned with the engine's orders")
    if not len(orders) or orders[0] != 0 or reasons[0] != "first" or "first" in reasons[1:]:
        raise ConsistencyError("the first buy must be the one order at close 0, with reason 'first'")
    if not set(reasons) <= set(REASONS) or (np.diff(orders) <= 0).any() or orders[-1] > n - 2:
        raise ConsistencyError("orders must be increasing closes 0 .. n-2 with reasons in " + str(REASONS))
    times = result.index.asi8
    ordinary = np.array(
        [times[t] for t, r in zip(orders, reasons, strict=True) if r not in ("first", "limit")]
    )
    most = _most_in(ordinary, MONTH_DAYS)
    allowed = math.ceil(MONTH_DAYS / wait)
    if most > allowed:
        raise ConsistencyError(
            f"{most} orders that are not limit orders in one 30-day stretch, more than ceil(30 / {wait}) = {allowed}"
        )
    clock = int(times[0]) if first_buy_waits else None
    for t, reason, flag in zip(orders[1:].tolist(), reasons[1:], in_wait[1:], strict=True):
        now = int(times[t])
        waiting = clock is not None and now - clock < wait * DAY_US
        if waiting and reason != "limit":
            raise ConsistencyError(
                f"a {reason} order at {result.index[t]} comes less than {wait} days after the previous order that "
                "starts the wait"
            )
        if flag != (reason == "limit" and waiting):
            raise ConsistencyError(f"the in-wait flag of the order at {result.index[t]} is wrong")
        clock = now
    if len(held) and (
        held[0] < 1 or held[-1] > n - 2 or (np.diff(held) <= 0).any() or np.isin(held, orders).any()
    ):
        raise ConsistencyError("held closes must be increasing closes 1 .. n-2 where no order was sent")


def _limit_value(value, name: str) -> float | None:
    return (
        None if value is None else _real(value, name, 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    )


def path_metrics(
    result: pd.DataFrame,
    *,
    targets,
    band: float,
    min_cash: float | None,
    max_coin: float | None,
    wait: int,
    first_buy_waits: bool = False,
) -> dict:
    """Closeness to target and the counts of section 8, from the result (after :func:`check_path`).

    Notation: n rows, E = rows 1 .. n-1 (row 0 is the all-cash close), span = (ts[n-1] - ts[0]) in days. The
    weights are the result's ``w_BTC``, ``w_ETH`` at each close: exactly what the rule sees there. Keys:

    - ``rows``, ``span_days``, ``wait_days`` (W, echoed);
    - ``rebalances`` (orders at closes 1 .. n-2, every reason), ``rebalances_band``, ``rebalances_limit``,
      ``rebalances_reset``, ``rebalances_per_30d`` = 30 * rebalances / span, ``rebalances_per_30d_no_limit``;
    - ``limit_in_wait`` and ``limit_in_wait_per_year`` (365 / span); ``held`` and ``held_per_year``;
    - ``max_in_30d``: the most counted orders in any [ts_i, ts_i + 30 days) starting at an order close;
    - ``legs`` (fill legs on rows >= 2) and ``legs_per_year``; ``empty_orders`` (counted orders that traded nothing);
    - ``in_band_share`` (closes of E where every coin with T > 0 has abs(w - T) <= b * T), ``out_days_per_year``
      (D_out = 365 * out-of-band closes of E / (n - 1)), ``longest_out_days`` (the longest run of consecutive
      out-of-band rows, ts of its last close - ts of its first + 1 day);
    - ``dist_mean`` and ``dist_worst``: d_t = max over the coins with T > 0 of abs(w - T) / T (0 without coins);
    - ``drift_mean_pts`` and ``drift_worst_pts``: 100 * abs(w_BTC + w_ETH - (T_BTC + T_ETH)), in points;
    - ``breach_closes``: closes of E where ``portfolio._breach_test(min_cash, max_coin)`` holds.
    """
    check_path(result, wait=wait, first_buy_waits=first_buy_waits)
    t_btc = _real(targets[0], "targets[0]", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    t_eth = _real(targets[1], "targets[1]", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    band = _real(band, "band", 0.0, low_inclusive=True)
    breached = _breach_test(_limit_value(min_cash, "min_cash"), _limit_value(max_coin, "max_coin"))
    times = result.index.asi8
    n = len(result)
    span = _span_days(times)
    w = result[list(WEIGHT_COLUMNS)].to_numpy(dtype=float)[1:]
    out = np.zeros(n - 1, dtype=bool)
    dist = np.zeros(n - 1)
    for a, target in enumerate((t_btc, t_eth)):
        if target > 0.0:
            dev = np.abs(w[:, a] - target)
            out |= dev > band * target
            dist = np.maximum(dist, dev / target)
    rows_out = np.flatnonzero(out) + 1
    longest = 0.0
    if len(rows_out):
        breaks = np.flatnonzero(np.diff(rows_out) != 1)
        starts = rows_out[np.concatenate(([0], breaks + 1))]
        ends = rows_out[np.concatenate((breaks, [len(rows_out) - 1]))]
        longest = float(_days(times[ends] - times[starts]).max() + 1.0)
    drift = 100.0 * np.abs(w[:, 0] + w[:, 1] - (t_btc + t_eth))
    reasons = np.asarray([str(r) for r in result.attrs["reasons"]], dtype=object)
    orders = np.asarray(result.attrs["orders"], dtype=np.int64)
    counted = reasons != "first"
    n_reb = int(counted.sum())
    by = {r: int((reasons == r).sum()) for r in ("band", "limit", "reset")}
    in_wait = int(np.asarray(result.attrs["in_wait"], dtype=bool).sum())
    held = len(result.attrs["held"])
    fills = result.attrs["fills"]
    legs = int((fills["bar"].to_numpy() >= 2).sum())
    turnover = result["turnover"].to_numpy()
    empty = int((turnover[orders[counted] + 1] == 0.0).sum())
    return {
        "rows": n,
        "span_days": span,
        "wait_days": wait,
        "rebalances": n_reb,
        "rebalances_band": by["band"],
        "rebalances_limit": by["limit"],
        "rebalances_reset": by["reset"],
        "rebalances_per_30d": MONTH_DAYS * n_reb / span,
        "rebalances_per_30d_no_limit": MONTH_DAYS * (n_reb - by["limit"]) / span,
        "limit_in_wait": in_wait,
        "limit_in_wait_per_year": YEAR_DAYS * in_wait / span,
        "held": held,
        "held_per_year": YEAR_DAYS * held / span,
        "max_in_30d": _most_in(times[orders[counted]], MONTH_DAYS),
        "legs": legs,
        "legs_per_year": YEAR_DAYS * legs / span,
        "empty_orders": empty,
        "in_band_share": float((~out).sum() / (n - 1)),
        "out_days_per_year": YEAR_DAYS * int(out.sum()) / (n - 1),
        "longest_out_days": longest,
        "dist_mean": float(dist.mean()),
        "dist_worst": float(dist.max()),
        "drift_mean_pts": float(drift.mean()),
        "drift_worst_pts": float(drift.max()),
        "breach_closes": int(sum(breached(tuple(row)) for row in w.tolist())),
    }


def trade_sizes(result: pd.DataFrame) -> dict:
    """Trade sizes from the fill log (section 8). Legs on rows >= 2 (the rebalances): ``max_leg_pct`` (the largest
    leg as % of the wallet just before its fill, V_open: 100 * abs(weight_after - weight_before)),
    ``max_day_turnover_pct`` (the largest fill row's legs together, 100 * turnover) and ``min_leg_usd`` (the
    smallest leg in USD); 0, 0 and NaN without such a leg. The first buy's legs (row 1) on their own:
    ``first_legs``, ``first_max_leg_pct``, ``first_turnover_pct`` and ``first_min_leg_usd`` (0, 0, 0, NaN when
    nothing was bought)."""
    fills = result.attrs["fills"]
    bar = fills["bar"].to_numpy()
    size = 100.0 * np.abs(
        fills["weight_after"].to_numpy(dtype=float) - fills["weight_before"].to_numpy(dtype=float)
    )
    usd = fills["usd"].to_numpy(dtype=float)
    turnover = result["turnover"].to_numpy(dtype=float)
    later, first = bar >= 2, bar == 1
    return {
        "max_leg_pct": float(size[later].max()) if later.any() else 0.0,
        "max_day_turnover_pct": float(100.0 * turnover[2:].max()) if len(turnover) > 2 else 0.0,
        "min_leg_usd": float(usd[later].min()) if later.any() else math.nan,
        "first_legs": int(first.sum()),
        "first_max_leg_pct": float(size[first].max()) if first.any() else 0.0,
        "first_turnover_pct": float(100.0 * turnover[1]),
        "first_min_leg_usd": float(usd[first].min()) if first.any() else math.nan,
    }


def money_metrics(result: pd.DataFrame, costs: Costs) -> dict:
    """Fees, gas, return, Sharpe and falls with their dates (section 8), from the result and its fill log.

    Fees and gas cover the legs on rows >= 2 (the rebalances), each over its V_open = usd / abs(weight change):
    ``fees_pct_per_year`` = 100 * 365 / span * sum((leg cost - gas) / V_open) (what the customer pays: gas is
    sponsored), ``gas_pct_per_year`` the same with the gas, and ``fees_usd_per_year``, ``gas_usd_per_year``. Every
    leg's cost must be ``usd * costs.rate(usd) + costs.gas_usd_per_trade`` bit for bit (the cost model the run used),
    and fees + gas must equal 100 * 365 / span * sum(cost[2:]) to 1e-12 relative, else :class:`ConsistencyError`.
    The first buy: ``first_cost_pct`` (100 * cost[1], % of the starting wallet), ``first_cost_usd`` and
    ``first_gas_usd``. Descriptions: ``total_return`` = prod(1 + ret[1:]) - 1, ``sharpe`` =
    ``stats.annualized_sharpe(ret[1:], 365)``; falls are signed fractions <= 0 on e_0 = 1 at close 0 and
    e_t = prod(1 + ret[1 .. t]): ``max_drawdown`` (equal to ``montecarlo.max_drawdown(ret[1:])``) with
    ``mdd_trough`` (the first close where e_t / max(e_0..e_t) - 1 is lowest) and ``mdd_peak`` (the first close at or
    before it where e equals that running maximum); ``worst_day`` = min(ret[1:]) with ``worst_day_close``;
    ``worst_week`` = min over closes u, t with ts_t = ts_u + 7 days of e_t / e_u - 1, with ``worst_week_start`` (u)
    and ``worst_week_end`` (t); NaN and NaT without such a pair (a pair ending on a missing close is skipped)."""
    if not isinstance(costs, Costs):
        raise ValueError(f"costs must be a Costs instance, got {type(costs).__name__}")
    times = result.index.asi8
    year = YEAR_DAYS / _span_days(times)
    fills = result.attrs["fills"]
    usd = fills["usd"].to_numpy(dtype=float)
    leg_cost = fills["cost"].to_numpy(dtype=float)
    gas = costs.gas_usd_per_trade
    expected = np.array([x * costs.rate(x) + gas for x in usd.tolist()], dtype=float)
    if not np.array_equal(leg_cost, expected):
        raise ConsistencyError("the fill log's leg costs are not usd * rate(usd) + gas of this cost model")
    v_open = usd / np.abs(
        fills["weight_after"].to_numpy(dtype=float) - fills["weight_before"].to_numpy(dtype=float)
    )
    bar = fills["bar"].to_numpy()
    later, first = bar >= 2, bar == 1
    fees = math.fsum(((leg_cost[later] - gas) / v_open[later]).tolist())
    gas_frac = math.fsum((gas / v_open[later]).tolist())
    cost = result["cost"].to_numpy(dtype=float)
    paid = math.fsum(cost[2:].tolist())
    if abs(fees + gas_frac - paid) > 1e-12 * abs(paid):
        raise ConsistencyError(
            f"customer fees + gas ({fees + gas_frac!r}) differ from the cost column ({paid!r})"
        )
    r = result["ret"].to_numpy(dtype=float)[1:]
    equity = np.cumprod(np.concatenate(([1.0], 1.0 + r)))
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    trough = int(np.argmin(dd))
    mdd = float(dd[trough])
    if mdd != max_drawdown(r):
        raise ConsistencyError(f"max drawdown {mdd!r} differs from montecarlo.max_drawdown")
    top = int(np.argmax(equity[: trough + 1] == peak[trough]))
    day = int(np.argmin(r)) + 1
    later_ends = np.searchsorted(times, times + 7 * DAY_US)
    pair = later_ends < len(times)
    pair[pair] = times[later_ends[pair]] == times[pair] + 7 * DAY_US
    week, week_start, week_end = math.nan, pd.NaT, pd.NaT
    if pair.any():
        starts = np.flatnonzero(pair)
        falls = equity[later_ends[starts]] / equity[starts] - 1.0
        i = int(np.argmin(falls))
        week = float(falls[i])
        week_start, week_end = result.index[starts[i]], result.index[later_ends[starts[i]]]
    return {
        "fees_pct_per_year": 100.0 * year * fees,
        "gas_pct_per_year": 100.0 * year * gas_frac,
        "fees_usd_per_year": year * math.fsum((leg_cost[later] - gas).tolist()),
        "gas_usd_per_year": year * gas * int(later.sum()),
        "first_cost_pct": 100.0 * float(cost[1]),
        "first_cost_usd": math.fsum(leg_cost[first].tolist()),
        "first_gas_usd": gas * int(first.sum()),
        "total_return": float(np.prod(1.0 + r) - 1.0),
        "sharpe": stats.annualized_sharpe(r, YEAR_DAYS),
        "max_drawdown": mdd,
        "mdd_peak": result.index[top],
        "mdd_trough": result.index[trough],
        "worst_day": float(r[day - 1]),
        "worst_day_close": result.index[day],
        "worst_week": week,
        "worst_week_start": week_start,
        "worst_week_end": week_end,
    }


def _part(name: str, data: bytes) -> bytes:
    return name.encode() + b"\0" + len(data).to_bytes(8, "little") + data


def path_hash(result: pd.DataFrame) -> str:
    """SHA-256 (hex) of what must not depend on costs or the wallet size (section 4.6): for each part in this
    order, its name, a zero byte, its byte length (8 bytes little-endian) and its bytes: ``orders`` (int64
    little-endian), ``reasons`` (joined by newlines, UTF-8), ``in_wait`` (one byte per order, 0 or 1), ``w_BTC`` and
    ``w_ETH`` (float64 little-endian, every row)."""
    attrs = result.attrs
    digest = hashlib.sha256()
    digest.update(_part("orders", np.asarray(attrs["orders"], dtype="<i8").tobytes()))
    digest.update(_part("reasons", "\n".join(str(r) for r in attrs["reasons"]).encode("utf-8")))
    digest.update(_part("in_wait", np.asarray(attrs["in_wait"], dtype=bool).astype(np.uint8).tobytes()))
    for col in WEIGHT_COLUMNS:
        digest.update(_part(col, result[col].to_numpy(dtype="<f8").tobytes()))
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------------------- windows


def _source(source) -> str:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    return source


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def rolling_windows(source: str) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    """Section 6's rolling 12-month windows, from the calendar only: window k starts in month M_k = January 2017 + k
    months and holds the bars of M_k .. M_(k+11) (a bar's day is its close minus 1 day), so its closes run from the
    2nd of M_k to the 1st of M_(k+12), both included, at 00:00 UTC. Kraken: k = 0 .. 59; Binance: the k whose first
    close is on or after its first close, 2017-08-18 (k = 8 .. 59). ``(k, first close, last close)``."""
    first_close = FIRST_CLOSE[_source(source)]
    month0 = pd.Timestamp("2017-01-01", tz="UTC")
    out = []
    for k in range(N_WINDOWS):
        first = month0 + pd.DateOffset(months=k) + pd.Timedelta(days=1)
        if first >= first_close:
            out.append((k, first, month0 + pd.DateOffset(months=k + 12)))
    return out


def full_window(source: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The full run's first and last close: Kraken 2017-01-02 .. 2023-01-01, Binance 2017-08-18 .. 2023-01-01."""
    return FIRST_CLOSE[_source(source)], LAST_CLOSE


def window_slice(panel: pd.DataFrame, first, last, *, missing: Iterable = ()) -> pd.DataFrame:
    """``panel.loc[first:last]``, refused (:class:`WindowSliceError`) unless its closes are exactly the daily closes
    first .. last (00:00 UTC grid) minus the source's pinned ``missing`` closes (``MISSING_CLOSES[source]``) inside
    the slice: a missing close or an extra one stops the run (section 6, stop rule 5)."""
    validate_panel(panel)
    first, last = _utc(first), _utc(last)
    piece = panel.loc[first:last]
    grid = pd.date_range(first, last, freq="D", unit="us")
    expected = grid[~grid.isin(pd.DatetimeIndex(list(missing), tz="UTC").as_unit("us"))]
    got = piece.index
    if not np.array_equal(got.asi8, expected.asi8):
        lacking = [ts.isoformat() for ts in expected.difference(got)]
        extra = [ts.isoformat() for ts in got.difference(expected)]
        raise WindowSliceError(
            f"slice {first.isoformat()} .. {last.isoformat()}: {len(got)} closes, expected {len(expected)}; "
            f"missing {lacking[:5]}, extra {extra[:5]}"
        )
    return piece


# ------------------------------------------------------------------------------------- the runs table and pools


def _rows(table: pd.DataFrame, **equal) -> pd.DataFrame:
    mask = np.ones(len(table), dtype=bool)
    for col, value in equal.items():
        mask &= table[col].to_numpy() == value
    return table[mask]


def _failed(*tables: pd.DataFrame) -> bool:
    return any((t["status"].to_numpy() != OK).any() for t in tables)


def pool(runs: pd.DataFrame, source: str, *, reading: str = "lab") -> pd.DataFrame:
    """One source's decision pool: its rolling grid runs without a reset. ``reading="lab"``: the lab's first-buy
    reading; ``"other"``: the other reading's runs (finite caps, 5,000 USD, 1x) plus the lab's no-cap runs at 5,000
    USD and 1x as their reference (with no cap the two readings make the same orders)."""
    if reading not in ("lab", "other"):
        raise ValueError(f"reading must be 'lab' or 'other', got {reading!r}")
    base = runs[
        (runs["source"].to_numpy() == _source(source))
        & (runs["scope"].to_numpy() == "rolling")
        & (runs["comparator"].to_numpy() == "grid")
        & runs["R"].isna().to_numpy()
    ]
    is_lab = base["reading"].to_numpy() == "lab"
    if reading == "lab":
        return base[is_lab]
    reference = (
        is_lab
        & (base["cap"].to_numpy() == "none")
        & (base["V"].to_numpy() == REF_BOOK)
        & (base["cost"].to_numpy() == "1x")
    )
    return base[(base["reading"].to_numpy() == "other") | reference]


def limit_only_pool(table: pd.DataFrame, source: str) -> pd.DataFrame:
    """One source's rolling limit-only rows (of the runs table or of ``limit_only_bands``)."""
    return table[
        (table["source"].to_numpy() == _source(source))
        & (table["scope"].to_numpy() == "rolling")
        & (table["comparator"].to_numpy() == "limit-only")
    ]


def drop_failed_pairs(runs: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple]]:
    """Rule E after triage found no code bug: drop every pair (one mix in one window of one source and scope) that
    holds a failed run, from every pool. Returns the kept rows and the dropped pairs ``(source, scope, window, s,
    f)``, sorted."""
    keys = ["source", "scope", "window", "s", "f"]
    bad = runs.loc[runs["status"].to_numpy() != OK, keys].drop_duplicates()
    dropped = sorted(tuple(row) for row in bad.itertuples(index=False, name=None))
    hit = pd.MultiIndex.from_frame(runs[keys]).isin(dropped) if dropped else np.zeros(len(runs), dtype=bool)
    return runs[~hit], dropped


def _pairs(rows: pd.DataFrame) -> list[tuple]:
    return sorted(set(rows[list(PAIR)].itertuples(index=False, name=None)))


def _pivot(rows: pd.DataFrame, value: str) -> pd.DataFrame:
    if rows[[*PAIR, "cap"]].duplicated().any():
        raise ValueError("the runs table holds two runs for one pair and cap")
    table = rows.pivot(index=list(PAIR), columns="cap", values=value)
    if set(table.columns) != set(CAP_LABELS) or table.isna().to_numpy().any():
        raise ValueError(f"every pair needs one run at each cap {CAP_LABELS}")
    return table[list(CAP_LABELS)]


def _band(band) -> float:
    if band not in BANDS:
        raise ValueError(f"band must be one of the grid bands {BANDS}, got {band!r}")
    return float(band)


def _cap_rank(cap: str) -> int:
    return len(FINITE_CAPS) if cap == MORE_THAN_8 else FINITE_CAPS.index(cap)


def _is_missing(value) -> bool:
    return isinstance(value, str) and value == MISSING


def _band_rank(band) -> int:
    return len(BANDS) if band == NO_BAND else BANDS.index(band)


def _tightest_run(passes: Mapping[str, bool]) -> str | None:
    """The tightest finite cap that passes with every looser finite cap passing too; None when 8 fails."""
    best = None
    for cap in reversed(FINITE_CAPS):
        if not passes[cap]:
            break
        best = cap
    return best


def _setting(book: float, cost: str) -> str:
    return f"{book:g}/{cost}"


REF_SETTING = _setting(REF_BOOK, "1x")

# -------------------------------------------------------------------------------------------------- rule B


def extra_out(runs: pd.DataFrame, band) -> pd.DataFrame | None:
    """extra_out(m, w; b, N) = D_out(b, N) - D_out(b, none) for every pair (index ``s, f, window``) and finite cap
    (columns, tightest first), from the 5,000 USD 1x runs of the pool; None when one of them failed (rule E)."""
    rows = _rows(runs, b=_band(band), V=REF_BOOK, cost="1x")
    if rows.empty:
        raise ValueError(f"no runs at band {band!r}, 5,000 USD and 1x")
    if _failed(rows):
        return None
    table = _pivot(rows, "out_days_per_year")
    return table[list(FINITE_CAPS)].sub(table["none"], axis=0)


def _extra_stats(extra: pd.DataFrame) -> dict:
    out = {}
    for cap in FINITE_CAPS:
        x = extra[cap].to_numpy(dtype=float)
        median, p90 = float(np.median(x)), float(np.percentile(x, 90))
        out[cap] = {
            "median": median,
            "p90": p90,
            "passes": median <= EXTRA_OUT_MEDIAN and p90 <= EXTRA_OUT_P90,
        }
    return out


def cap_for_band(runs: pd.DataFrame, band) -> dict:
    """Rule B: for each finite cap, the median and 90th percentile of extra_out over the pairs; N passes when the
    median is <= 7 days and the 90th percentile <= 30 days. ``N_star`` is the tightest finite cap that passes with
    every looser finite cap passing; "more than 8" when 8 fails; "MISSING" when the pool holds a failed run."""
    extra = extra_out(runs, band)
    if extra is None:
        return {"band": float(band), "N_star": MISSING, "pairs": None, "caps": None}
    caps = _extra_stats(extra)
    best = _tightest_run({cap: caps[cap]["passes"] for cap in FINITE_CAPS})
    return {
        "band": float(band),
        "N_star": MORE_THAN_8 if best is None else best,
        "pairs": len(extra),
        "caps": caps,
    }


# -------------------------------------------------------------------------------------------------- rule A


def acceptable(runs: pd.DataFrame, band, cap: str, book: float, cost: str) -> dict:
    """Rule A's conditions at one band and finite cap: (i) the median rebalances per 30 days over the pairs (from
    the 5,000 USD 1x runs) <= 1.0 and (ii) the median customer fees at (book, cost) <= 0.25% a year.
    ``acceptable`` is True, False or "MISSING" (a failed run in either pool)."""
    if cap not in FINITE_CAPS:
        raise ValueError(f"cap must be one of {FINITE_CAPS}, got {cap!r}")
    ref = _rows(runs, b=_band(band), cap=cap, V=REF_BOOK, cost="1x")
    at = _rows(runs, b=float(band), cap=cap, V=book, cost=cost)
    if ref.empty or _pairs(ref) != _pairs(at) or len(at) != len(ref):
        raise ValueError(
            f"band {band!r}, cap {cap}: the runs at {_setting(book, cost)} must be the pairs of {REF_SETTING}"
        )
    if _failed(ref, at):
        return {"rate_median": None, "fees_median": None, "acceptable": MISSING}
    rate = float(np.median(ref["rebalances_per_30d"].to_numpy(dtype=float)))
    fees = float(np.median(at["fees_pct_per_year"].to_numpy(dtype=float)))
    return {"rate_median": rate, "fees_median": fees, "acceptable": rate <= RATE_MAX and fees <= FEE_MAX}


def _caps_by_band(caps: Mapping) -> dict:
    allowed = (*FINITE_CAPS, MORE_THAN_8, MISSING)
    if not isinstance(caps, Mapping) or set(caps) != set(BANDS) or any(caps[b] not in allowed for b in BANDS):
        raise ValueError(f"caps must map each band of {BANDS} to one of {allowed}, got {caps!r}")
    return {b: caps[b] for b in BANDS}


def _narrowest(accepted: Mapping) -> float | str:
    """The narrowest band that is acceptable with every wider band acceptable; "none" when 0.50 is not; "MISSING"
    when any band's acceptability is MISSING."""
    if any(_is_missing(v) for v in accepted.values()):
        return MISSING
    best = NO_BAND
    for b in sorted(accepted, key=_band_rank, reverse=True):
        if not accepted[b]:
            break
        best = b
    return best


def _headline_of(b_star, caps: Mapping) -> tuple:
    """The band and cap to report for a b*: b* with N*(b*); for "none", 0.50 with N*(0.50); MISSING stays."""
    if b_star == MISSING:
        return MISSING, MISSING
    band = BANDS[-1] if b_star == NO_BAND else b_star
    return band, caps[band]


def default_band(runs: pd.DataFrame, caps: Mapping, book: float, cost: str) -> dict:
    """Rule A at one wallet size and cost level, with ``caps`` = {band: N*(band)} (rule B or its robust value): a
    band is acceptable when N*(b) is a number and :func:`acceptable` holds at (b, N*(b)). ``b_star`` is the narrowest
    band that is acceptable with every wider band acceptable; "none" (flagged NO BAND MET THE CONDITIONS, and 0.50
    with N*(0.50) reported) when 0.50 is not acceptable; "MISSING" when any band is."""
    caps = _caps_by_band(caps)
    bands = {}
    for b in BANDS:
        n = caps[b]
        if n in FINITE_CAPS:
            bands[b] = {"N": n, **acceptable(runs, b, n, book, cost)}
        else:
            bands[b] = {
                "N": n,
                "rate_median": None,
                "fees_median": None,
                "acceptable": MISSING if n == MISSING else False,
            }
    b_star = _narrowest({b: bands[b]["acceptable"] for b in BANDS})
    band, cap = _headline_of(b_star, caps)
    return {
        "book": float(book),
        "cost": cost,
        "b_star": b_star,
        "flag": NO_BAND_FLAG if b_star == NO_BAND else None,
        "band": band,
        "cap": cap,
        "caps": caps,
        "bands": bands,
    }


def _widest(values: Iterable) -> float | str:
    values = list(values)
    if MISSING in values:
        return MISSING
    return max(values, key=_band_rank)


def app_default(defaults: Sequence[Mapping]) -> dict:
    """The app's single default from rule A's results at one cost level for each wallet size: the widest b* ("none"
    counts as wider than 0.50, flagged), with that band's N*; ``per_book`` lists each size's b*."""
    caps = defaults[0]["caps"]
    if any(d["caps"] != caps or d["cost"] != defaults[0]["cost"] for d in defaults):
        raise ValueError("app_default needs rule A's results for one cost level and one caps mapping")
    per_book = {d["book"]: d["b_star"] for d in defaults}
    widest = _widest(per_book.values())
    band, cap = _headline_of(widest, caps)
    return {
        "b_star": widest,
        "flag": NO_BAND_FLAG if widest == NO_BAND else None,
        "band": band,
        "cap": cap,
        "per_book": per_book,
        "per_book_differs": len(set(per_book.values())) > 1,
    }


# -------------------------------------------------------------------------------------------------- rule C


def _cap_means(rows: pd.DataFrame, value: str) -> dict:
    counts = rows["cap"].value_counts()
    if set(counts.index) != set(CAP_LABELS) or counts.nunique() != 1:
        raise ValueError(f"every cap {CAP_LABELS} needs the same number of runs")
    means = rows.groupby("cap")[value].mean()
    return {cap: float(means[cap]) for cap in CAP_LABELS}


def _bought(start: float, values: Mapping) -> dict:
    """(start - X(N)) / (start - X(none)) for every cap; None for every cap when start - X(none) <= 0."""
    den = start - values["none"]
    return {cap: (start - values[cap]) / den if den > 0 else None for cap in CAP_LABELS}


def _outcome(start: float, values: Mapping, shares: Mapping) -> tuple[str, str | None]:
    """Rule C's outcome, in its pinned order: NO EVIDENCE when start - X(none) <= 0; else ABOVE 8 when no finite cap
    has I >= 0.90 at it and at every looser finite cap; else EVIDENCE at the tightest such cap."""
    if not start - values["none"] > 0:
        return NO_EVIDENCE, None
    best = _tightest_run({cap: shares[cap] >= CLOSE_SHARE for cap in FINITE_CAPS})
    return (ABOVE_8, None) if best is None else (EVIDENCE, best)


def _value_test(i, c) -> str:
    """SUPPORTED when 1 - C >= 2 * (1 - I); WEAK otherwise, and whenever I or C is undefined (None)."""
    return SUPPORTED if i is not None and c is not None and 1.0 - c >= VALUE_FACTOR * (1.0 - i) else WEAK


def outcome_label(outcome: str, n_up: str | None, value: str | None = None) -> str:
    """Rule C's outcome in words: "EVIDENCE FOR A LIMIT AT 2, value test SUPPORTED", "ABOVE 8", "NO EVIDENCE"."""
    if outcome != EVIDENCE:
        return outcome
    return f"{EVIDENCE} AT {n_up}" + ("" if value is None else f", value test {value}")


def upper_limit(
    runs: pd.DataFrame,
    limit_only: pd.DataFrame,
    book: float,
    cost: str,
    *,
    limit_only_bands: pd.DataFrame | None = None,
) -> dict:
    """Rule C at one wallet size and cost level, on one source's pool (all 6 bands) and its limit-only runs.

    Dist(N) = mean d-bar over the pool at cap N (5,000 USD 1x), Dist_L the same over the limit-only runs of the same
    mixes and windows; I(N) = (Dist_L - Dist(N)) / (Dist_L - Dist(none)). F(N) and F_L: mean customer fees at
    (book, cost); C(N) = (F(N) - F_L) / (F(none) - F_L), undefined (None) when F(none) - F_L <= 0. Outcome, in this
    order: NO EVIDENCE (Dist_L - Dist(none) <= 0), ABOVE 8, or EVIDENCE FOR A LIMIT AT N_up (the tightest finite cap
    with I >= 0.90 at it and every looser finite cap), with the value test (SUPPORTED when 1 - C(N_up) >= 2 * (1 -
    I(N_up)), else WEAK) and the bands it would hold back (N*(b) above N_up, or "more than 8"). Descriptions: I(N)
    and N_up per band; with ``limit_only_bands``, the days-outside-the-band yardstick (D_out for d-bar); and gas per
    customer a year at each cap (USD and % of ``book``). "MISSING" when a pool holds a failed run."""
    ref, at = _rows(runs, V=REF_BOOK, cost="1x"), _rows(runs, V=book, cost=cost)
    lo_ref, lo_at = _rows(limit_only, V=REF_BOOK, cost="1x"), _rows(limit_only, V=book, cost=cost)
    pairs = _pairs(ref)
    if (
        set(ref["b"]) != set(BANDS)
        or _pairs(at) != pairs
        or _pairs(lo_ref) != pairs
        or _pairs(lo_at) != pairs
    ):
        raise ValueError(
            f"rule C needs every band of {BANDS} and limit-only runs of the same mixes and windows at "
            f"{REF_SETTING} and {_setting(book, cost)}"
        )
    lob = None if limit_only_bands is None else _rows(limit_only_bands, V=REF_BOOK, cost="1x")
    base = {"book": float(book), "cost": cost, "status": STATUS}
    if _failed(ref, at, lo_ref, lo_at, *(() if lob is None else (lob,))):
        return {**base, "outcome": MISSING, "N_up": None, "value_test": None, "label": MISSING}
    dist, dist_l = _cap_means(ref, "dist_mean"), float(lo_ref["dist_mean"].mean())
    shares = _bought(dist_l, dist)
    fees, fees_l = _cap_means(at, "fees_pct_per_year"), float(lo_at["fees_pct_per_year"].mean())
    spent = _bought(-fees_l, {cap: -v for cap, v in fees.items()})
    outcome, n_up = _outcome(dist_l, dist, shares)
    value = _value_test(shares[n_up], spent[n_up]) if outcome == EVIDENCE else None
    held_back = None
    if (
        outcome == EVIDENCE
    ):  # no N* is MISSING here: a failed 5,000 USD 1x run made the whole rule MISSING above
        stars = {b: cap_for_band(runs, b)["N_star"] for b in BANDS}
        held_back = [b for b in BANDS if _cap_rank(stars[b]) > _cap_rank(n_up)]
    per_band = {}
    for b in BANDS:
        d_b = _cap_means(_rows(ref, b=b), "dist_mean")
        s_b = _bought(dist_l, d_b)
        o_b, n_b = _outcome(dist_l, d_b, s_b)
        per_band[b] = {"Dist": d_b, "I": s_b, "outcome": o_b, "N_up": n_b}
    days = None
    if lob is not None:
        if set(lob["b"]) != set(BANDS) or len(lob) != len(BANDS) * len(pairs) or _pairs(lob) != pairs:
            raise ValueError(
                "limit_only_bands needs one row per band for every pair of the pool, at 5,000 USD and 1x"
            )
        d_out, d_l = _cap_means(ref, "out_days_per_year"), float(lob["out_days_per_year"].mean())
        d_shares = _bought(d_l, d_out)
        d_outcome, d_n = _outcome(d_l, d_out, d_shares)
        days = {"D_out": d_out, "D_out_L": d_l, "I": d_shares, "outcome": d_outcome, "N_up": d_n}
    gas = _cap_means(at, "gas_usd_per_year")
    gas_l = float(lo_at["gas_usd_per_year"].mean())
    return {
        **base,
        "outcome": outcome,
        "N_up": n_up,
        "value_test": value,
        "label": outcome_label(outcome, n_up, value),
        "Dist": dist,
        "Dist_L": dist_l,
        "I": shares,
        "F": fees,
        "F_L": fees_l,
        "C": spent,
        "held_back": held_back,
        "per_band": per_band,
        "days": days,
        "gas": {
            **{cap: {"usd": v, "pct": 100.0 * v / book} for cap, v in gas.items()},
            "limit-only": {"usd": gas_l, "pct": 100.0 * gas_l / book},
        },
    }


# ------------------------------------------------------------------------------------- one source, then rule D


def decide_source(
    runs: pd.DataFrame,
    limit_only: pd.DataFrame,
    *,
    limit_only_bands: pd.DataFrame | None = None,
    books: Sequence[float] = BOOKS,
    costs: Sequence[str] = COST_LABELS,
) -> dict:
    """Rules B, A and C on one source's pool (:func:`pool`) and its limit-only rows (:func:`limit_only_pool`):
    ``N_star`` and ``rule_B`` per band; ``accept`` = :func:`acceptable` at every band, finite cap and setting
    ("5000/1x", ...), which rule D reads; ``rule_A`` per setting; ``app_default`` per cost level (the widest b* over
    the wallet sizes); ``rule_C`` per setting."""
    sources = set(runs["source"]) | set(limit_only["source"])
    if len(sources) != 1:
        raise ValueError(f"decide_source needs one source's pool, got {sorted(sources)}")
    settings = [(book, cost) for cost in costs for book in books]
    rule_b = {b: cap_for_band(runs, b) for b in BANDS}
    stars = {b: rule_b[b]["N_star"] for b in BANDS}
    accept = {
        b: {cap: {_setting(*st): acceptable(runs, b, cap, *st) for st in settings} for cap in FINITE_CAPS}
        for b in BANDS
    }
    rule_a = {_setting(*st): default_band(runs, stars, *st) for st in settings}
    return {
        "source": sources.pop(),
        "N_star": stars,
        "rule_B": rule_b,
        "accept": accept,
        "rule_A": rule_a,
        "app_default": {cost: app_default([rule_a[_setting(b, cost)] for b in books]) for cost in costs},
        "rule_C": {
            _setting(*st): upper_limit(runs, limit_only, *st, limit_only_bands=limit_only_bands)
            for st in settings
        },
    }


def _larger_cap(a: str, b: str) -> str:
    if MISSING in (a, b):
        return MISSING
    return max(a, b, key=_cap_rank)


def _outcome_rank(outcome: str, n_up: str | None) -> int:
    return _cap_rank(n_up) if outcome == EVIDENCE else len(FINITE_CAPS)


def _robust_outcome(kraken: Mapping, binance: Mapping) -> tuple[str, str | None, bool]:
    """(outcome, N_up, one source said NO EVIDENCE)."""
    pair = ((kraken["outcome"], kraken["N_up"]), (binance["outcome"], binance["N_up"]))
    if MISSING in (pair[0][0], pair[1][0]):
        return MISSING, None, False
    evidence = [p for p in pair if p[0] != NO_EVIDENCE]
    if not evidence:
        return NO_EVIDENCE, None, False
    outcome, n_up = max(evidence, key=lambda p: _outcome_rank(*p))
    return outcome, n_up, len(evidence) == 1


def _conflict(stars: Mapping, b_star, outcome: str, n_up: str | None):
    """CONFLICT: N_up is a number and the default band is "none" or has N*(b*) above it. None when N_up is not a
    number; "MISSING" when b* is."""
    if outcome != EVIDENCE:
        return None
    if b_star == MISSING:
        return MISSING
    return b_star == NO_BAND or _cap_rank(stars[b_star]) > _cap_rank(n_up)


def _under_limit(stars: Mapping, accepted: Callable, n_up: str, books: Sequence[float]) -> dict:
    """The default under the limit: per wallet size, the narrowest band with N* <= N_up that is acceptable, with
    every wider band that also has N* <= N_up acceptable too ("none" if none qualifies); then the widest."""
    candidates = [b for b in BANDS if stars[b] in FINITE_CAPS and _cap_rank(stars[b]) <= _cap_rank(n_up)]
    per_book = {book: _narrowest({b: accepted(b, book) for b in candidates}) for book in books}
    widest = _widest(per_book.values())
    return {"b_star": widest, "cap": stars[widest] if widest in BANDS else None, "per_book": per_book}


def _under_pair(under: Mapping | None):
    return None if under is None else (under["b_star"], under["cap"])


def robust(primary: Mapping, binance: Mapping) -> dict:
    """Rule D from two :func:`decide_source` bundles (``primary`` = Kraken, ``binance``).

    - ``N_star``: N*_rob(b) = the larger of the two sources' N*(b) ("more than 8" the largest);
    - ``b_star``: per wallet size, the narrowest band acceptable at (b, N*_rob(b)) on both sources at both cost
      levels with every wider band acceptable too; ``app_default`` the widest over the wallet sizes;
    - ``outcome``/``N_up``: the larger of the two sources' rule C outcomes at 5,000 USD 1x (EVIDENCE AT 0.25 < ... <
      8 < ABOVE 8); NO EVIDENCE only if both say so; if exactly one does, the other's, labelled NOT ROBUST;
    - ``value_test``: at N_up,rob on each source, with I(N_up,rob) and C(N_up,rob) at 5,000 USD 1x and 2x: SUPPORTED
      only if all four tests pass (an undefined I or C fails); none at ABOVE 8 or NO EVIDENCE;
    - ``held_back``: the bands with N*_rob(b) above N_up,rob or "more than 8";
    - ``conflict``: N_up,rob a number and the robust default band "none" or with N*_rob above N_up,rob; then
      ``under_limit`` (:func:`_under_limit`). ``primary_check`` is the same check on the primary values (Kraken,
      1x, its N_up);
    - ``headline``: the band and cap to report (0.50 with N*_rob(0.50), or no cap if that is "more than 8", when no
      band met the conditions); ``label``: ROBUST when every robust value equals the primary one (N*(b), b*(V), the
      app default, N_up, the value test, the CONFLICT flag and the default under the limit: amendment A6) and no
      single source said NO EVIDENCE, else NOT ROBUST with ``moved`` naming each value and the settings whose own
      value differs.
    """
    sources = {"KRAKEN": primary, "BINANCE": binance}
    other_settings = (("KRAKEN", "2x"), ("BINANCE", "1x"), ("BINANCE", "2x"))
    stars = {b: _larger_cap(primary["N_star"][b], binance["N_star"][b]) for b in BANDS}

    def accepted(b, book):
        n = stars[b]
        if n not in FINITE_CAPS:
            return n if n == MISSING else False
        values = [
            sources[s]["accept"][b][n][_setting(book, c)]["acceptable"] for s in sources for c in COST_LABELS
        ]
        return MISSING if MISSING in values else all(values)

    b_star = {book: _narrowest({b: accepted(b, book) for b in BANDS}) for book in BOOKS}
    app = _widest(b_star.values())
    outcome, n_up, one_source = _robust_outcome(
        primary["rule_C"][REF_SETTING], binance["rule_C"][REF_SETTING]
    )
    tests, value = None, None
    if outcome == EVIDENCE:
        tests = {
            f"{s} {c}": _value_test(
                sources[s]["rule_C"][REF_SETTING]["I"][n_up],
                sources[s]["rule_C"][_setting(REF_BOOK, c)]["C"][n_up],
            )
            for s in sources
            for c in COST_LABELS
        }
        value = SUPPORTED if all(t == SUPPORTED for t in tests.values()) else WEAK
    # under EVIDENCE no N* is MISSING: a source's MISSING N* comes from a failed 5,000 USD 1x run, which makes its
    # rule C MISSING and the robust outcome MISSING (bundles from decide_source)
    held_back = [b for b in BANDS if _cap_rank(stars[b]) > _cap_rank(n_up)] if outcome == EVIDENCE else None
    conflict = _conflict(stars, app, outcome, n_up)
    under = _under_limit(stars, accepted, n_up, BOOKS) if conflict is True else None

    k_stars = primary["N_star"]
    k_c = primary["rule_C"][REF_SETTING]
    k_app = primary["app_default"]["1x"]["b_star"]
    k_conflict = _conflict(k_stars, k_app, k_c["outcome"], k_c["N_up"])
    k_under = None
    if k_conflict is True:
        k_under = _under_limit(
            k_stars,
            lambda b, book: primary["rule_A"][_setting(book, "1x")]["bands"][b]["acceptable"],
            k_c["N_up"],
            BOOKS,
        )
    primary_check = {"conflict": k_conflict, "under_limit": k_under}

    def own(s, c, what):
        bundle = sources[s]
        if what == "outcome":
            r = bundle["rule_C"][REF_SETTING]
            return outcome_label(r["outcome"], r["N_up"])
        if what == "value_test":
            return bundle["rule_C"][_setting(REF_BOOK, c)]["value_test"]
        if what == "app_default":
            return bundle["app_default"][c]["b_star"]
        return bundle["rule_A"][_setting(what, c)]["b_star"]

    rob_label = outcome_label(outcome, n_up)
    pri_label = outcome_label(k_c["outcome"], k_c["N_up"])
    compared = [
        *(
            (f"N*({b})", k_stars[b], stars[b], ["BINANCE"] if binance["N_star"][b] != k_stars[b] else [])
            for b in BANDS
        ),
        *(
            (f"b*({book:g})", primary["rule_A"][_setting(book, "1x")]["b_star"], b_star[book], book)
            for book in BOOKS
        ),
        ("app default", k_app, app, "app_default"),
        ("N_up", pri_label, rob_label, "outcome"),
        ("value test", k_c["value_test"], value, "value_test"),
        ("CONFLICT", k_conflict, conflict, ["rule D, from the values above"]),
        (
            "default under the limit",
            _under_pair(k_under),
            _under_pair(under),
            ["rule D, acceptable on both sources at both cost levels"],
        ),
    ]
    moved = []
    for name, pv, rv, how in compared:
        if pv == rv:
            continue
        if not isinstance(how, list):
            base = own("KRAKEN", "1x", how)
            how = [f"{s} {c}" for s, c in other_settings if own(s, c, how) != base]
        moved.append({"value": name, "primary": pv, "robust": rv, "settings": how})
    if one_source:
        moved.append(
            {
                "value": "N_up",
                "primary": pri_label,
                "robust": rob_label,
                "settings": ["one source NO EVIDENCE"],
            }
        )
    values = [*stars.values(), *b_star.values(), app, outcome]
    label = MISSING if MISSING in values else (NOT_ROBUST if moved else ROBUST)
    band, cap = _headline_of(app, stars)
    return {
        "N_star": stars,
        "b_star": b_star,
        "app_default": app,
        "flag": NO_BAND_FLAG if app == NO_BAND else None,
        "outcome": outcome,
        "N_up": n_up,
        "outcome_label": outcome_label(outcome, n_up, value),
        "one_source_no_evidence": one_source,
        "value_tests": tests,
        "value_test": value,
        "held_back": held_back,
        "conflict": conflict,
        "under_limit": under,
        "primary_check": primary_check,
        "headline": {"band": band, "cap": "none" if cap == MORE_THAN_8 else cap},
        "label": label,
        "moved": moved,
        "status": STATUS,
    }


# --------------------------------------------------------------------------------------------- descriptions


def _subset(table: pd.DataFrame, keep: Callable[[float], bool]) -> pd.DataFrame:
    return table[np.array([bool(keep(s)) for s in table["s"].tolist()], dtype=bool)]


def descriptions(
    runs: pd.DataFrame, limit_only: pd.DataFrame, *, limit_only_bands: pd.DataFrame | None = None
) -> dict:
    """Section 9's pre-registered descriptions, per source present in ``runs`` (the runs table; ``limit_only`` holds
    its limit-only rows, or is the same table):

    - ``other_reading``: rule B per band and rule A at 5,000 USD 1x on the other first-buy reading's pool
      (:func:`pool` with ``reading="other"``); None when the source has no such runs;
    - ``limit_readings``: rules A-C (:func:`decide_source`) on the 12 mixes with s >= 0.42 (``cash``: 60% would also
      cap cash) and on the 20 with s <= 0.58 (``together``: 60% would cap the two coins together);
    - ``years``: rule B's median and 90th percentile of extra_out per band and cap, by window start year
      (2017 + k // 12), and ``non_overlapping`` on the windows k = 0, 12, 24, 36, 48 the source has."""
    out = {}
    for source in [s for s in SOURCES if s in set(runs["source"])]:
        lab = pool(runs, source)
        lo = limit_only_pool(limit_only, source)
        lob = None if limit_only_bands is None else limit_only_pool(limit_only_bands, source)
        other = pool(runs, source, reading="other")
        other_reading = None
        if (other["reading"].to_numpy() == "other").any():
            stars = {b: cap_for_band(other, b)["N_star"] for b in BANDS}
            other_reading = {"N_star": stars, "rule_A": default_band(other, stars, REF_BOOK, "1x")}
        readings = {}
        for name, keep in (
            ("cash", lambda s: s >= CASH_READING_MIN_S),
            ("together", lambda s: s <= TOGETHER_READING_MAX_S),
        ):
            kept = _subset(lab, keep)
            readings[name] = {
                "mixes": len(set(zip(kept["s"], kept["f"], strict=True))),
                "decisions": decide_source(
                    kept, _subset(lo, keep), limit_only_bands=None if lob is None else _subset(lob, keep)
                ),
            }
        years: dict = {}
        non_overlapping: dict = {}
        for b in BANDS:
            extra = extra_out(lab, b)
            if extra is None:
                years[b] = non_overlapping[b] = MISSING
                continue
            k = extra.index.get_level_values("window").to_numpy()
            years[b] = {int(y): _extra_stats(extra[2017 + k // 12 == y]) for y in sorted(set(2017 + k // 12))}
            chosen = np.isin(k, NON_OVERLAPPING)
            non_overlapping[b] = _extra_stats(extra[chosen]) if chosen.any() else None
        out[source] = {
            "other_reading": other_reading,
            "limit_readings": readings,
            "years": years,
            "non_overlapping": non_overlapping,
            "non_overlapping_windows": sorted(set(pool(runs, source)["window"]) & set(NON_OVERLAPPING)),
        }
    return out


# ------------------------------------------------------------------------------------------------------ falls

FALLS_COLUMNS = (
    "source",
    "level",
    "s",
    "f",
    "band",
    "cap",
    "missing",
    "window_fall_pct",
    "window_k",
    "window_first",
    "window_last",
    "window_f",
    "full_fall_pct",
    "full_peak",
    "full_trough",
    "full_f",
    "full_reset_fall_pct",
    "full_reset_peak",
    "full_reset_trough",
    "full_reset_f",
    "grid_fall_pct",
    "grid_b",
    "grid_cap",
    "grid_k",
    "grid_f",
    "worst_day_pct",
    "worst_day_close",
    "worst_day_f",
    "worst_week_pct",
    "worst_week_start",
    "worst_week_end",
    "worst_week_f",
    "label",
    "note",
)


def _fall(value) -> float:
    """A signed fall (<= 0) as the positive size the tables show: -100 * value."""
    return -100.0 * float(value)


def _worst(rows: pd.DataFrame, value: str, order: Sequence[str]) -> pd.Series | None:
    """The row with the lowest ``value`` (ties: the first in ``order``); None if a row failed or none exist."""
    if rows.empty or _failed(rows):
        return None
    rows = rows.assign(_cap_rank=rows["cap"].map(CAP_LABELS.index))
    rows = rows.sort_values([c if c != "cap" else "_cap_rank" for c in order], kind="stable")
    return rows.iloc[int(np.argmin(rows[value].to_numpy(dtype=float)))]


def _mix_falls(src: pd.DataFrame, s: float, f: float, band: float, cap: str) -> dict:
    mix = _rows(src, s=s, f=f)
    no_reset = mix["R"].isna().to_numpy()
    rolling = mix[(mix["scope"].to_numpy() == "rolling") & no_reset]
    full = mix[
        (mix["scope"].to_numpy() == "full") & (mix["b"].to_numpy() == band) & (mix["cap"].to_numpy() == cap)
    ]
    pieces = {
        "window": _worst(_rows(rolling, b=band, cap=cap), "max_drawdown", ["window"]),
        "full": _worst(full[full["R"].isna().to_numpy()], "max_drawdown", ["window"]),
        "full_reset": _worst(full[full["R"].to_numpy() == RESET_DAYS], "max_drawdown", ["window"]),
        "grid": _worst(rolling, "max_drawdown", ["b", "cap", "window"]),
    }
    row = dict.fromkeys(FALLS_COLUMNS)
    row.update(
        {
            "level": "mix",
            "s": s,
            "f": f,
            "band": band,
            "cap": cap,
            "missing": any(p is None for p in pieces.values()),
        }
    )
    if row["missing"]:
        return row
    w, fu, fr, g = pieces["window"], pieces["full"], pieces["full_reset"], pieces["grid"]
    row.update(
        {
            "window_fall_pct": _fall(w["max_drawdown"]),
            "window_k": int(w["window"]),
            "window_first": w["first_close"],
            "window_last": w["last_close"],
            "full_fall_pct": _fall(fu["max_drawdown"]),
            "full_peak": fu["mdd_peak"],
            "full_trough": fu["mdd_trough"],
            "full_reset_fall_pct": _fall(fr["max_drawdown"]),
            "full_reset_peak": fr["mdd_peak"],
            "full_reset_trough": fr["mdd_trough"],
            "grid_fall_pct": _fall(g["max_drawdown"]),
            "grid_b": float(g["b"]),
            "grid_cap": g["cap"],
            "grid_k": int(g["window"]),
            "worst_day_pct": _fall(fu["worst_day"]),
            "worst_day_close": fu["worst_day_close"],
            "worst_week_pct": _fall(fu["worst_week"]),
            "worst_week_start": fu["worst_week_start"],
            "worst_week_end": fu["worst_week_end"],
        }
    )
    for name in ("window", "full", "full_reset", "grid", "worst_day", "worst_week"):
        row[f"{name}_f"] = f
    return row


_SHARE_GROUPS = {
    "window": ("window_fall_pct", "window_k", "window_first", "window_last"),
    "full": ("full_fall_pct", "full_peak", "full_trough"),
    "full_reset": ("full_reset_fall_pct", "full_reset_peak", "full_reset_trough"),
    "grid": ("grid_fall_pct", "grid_b", "grid_cap", "grid_k"),
    "worst_day": ("worst_day_pct", "worst_day_close"),
    "worst_week": ("worst_week_pct", "worst_week_start", "worst_week_end"),
}


def _share_falls(s: float, band: float, cap: str, mixes: Sequence[dict]) -> dict:
    row = dict.fromkeys(FALLS_COLUMNS)
    row.update(
        {"level": "share", "s": s, "band": band, "cap": cap, "missing": any(m["missing"] for m in mixes)}
    )
    if row["missing"]:
        return row
    for name, cols in _SHARE_GROUPS.items():
        worst = mixes[
            int(np.argmax([m[cols[0]] for m in mixes]))
        ]  # the largest positive size; ties: the first f
        row.update({c: worst[c] for c in cols})
        row[f"{name}_f"] = worst[f"{name}_f"]
    return row


def falls_tables(runs: pd.DataFrame, headline: Mapping) -> pd.DataFrame:
    """Section 10's falls (A3), from the runs table, at 5,000 USD and 1x, the lab's reading, for each source present:
    by crypto share first (a ``share`` row: the worst of its mixes for each measure, naming the mix's f), then by
    mix (``mix`` rows), each at the headline band and cap (``headline`` = {"band": b, "cap": label}):

    - ``window_*``: the worst fall over the rolling windows (no reset), naming the window k and its closes;
    - ``full_*`` and ``full_reset_*``: the full run's fall with its peak and trough, without and with the yearly
      reset;
    - ``grid_*``: the deepest fall over every band and cap of the grid for the mix (rolling, no reset), naming them;
    - ``worst_day_*``, ``worst_week_*``: from the full run without reset, with their dates.

    Every fall is a positive size, -100 * the signed number, so the worst is the minimum of the signed number (ties:
    the first window, band and cap in grid order; the first f). A mix whose rows include a failed run, or lack one,
    is ``missing`` with no numbers, and so is its share row. Every row carries :data:`LABEL` and :data:`FALLS_NOTE`."""
    band, cap = _band(headline["band"]), headline["cap"]
    if cap not in CAP_LABELS:
        raise ValueError(f"headline cap must be one of {CAP_LABELS}, got {cap!r}")
    base = _rows(runs, comparator="grid", reading="lab", V=REF_BOOK, cost="1x")
    rows = []
    for source in [s for s in SOURCES if s in set(base["source"])]:
        src = _rows(base, source=source)
        present = set(zip(src["s"].tolist(), src["f"].tolist(), strict=True))
        for s in S_VALUES:
            mixes = [
                {**_mix_falls(src, s, f, band, cap), "source": source}
                for s2, f in MIXES
                if (s2, f) in present and s2 == s
            ]
            if mixes:
                rows.append({**_share_falls(s, band, cap, mixes), "source": source})
                rows.extend(mixes)
    table = pd.DataFrame(rows, columns=list(FALLS_COLUMNS))
    table["label"] = LABEL
    table["note"] = FALLS_NOTE
    return table


# ------------------------------------------------------------------------- the boom-year addendum (amendment A5)

TRAIN_YEARS = (2017, 2018, 2019, 2020, 2021, 2022)
BOOM_RANK_SOURCE = "KRAKEN"  # the years are ranked on Kraken's BTC closes for both sources (A5)
BOOM_MIN_WINDOWS = 12  # a removal that leaves a source fewer windows is MISSING (A5)
BOOM_LABEL = (
    "ADDENDUM (owner decision 2026-11-21, PLAN.md A5): the decision rules recomputed without each train year and "
    "without the best one and two years; reported next to the pre-registered headline, never in place of it. "
    + LABEL
)


def bar_years(index: pd.DatetimeIndex) -> np.ndarray:
    """The calendar year of each bar: its close time minus 1 day (section 6)."""
    return (pd.DatetimeIndex(index) - pd.Timedelta(days=1)).year.to_numpy()


def year_returns(panel: pd.DataFrame, asset: str = "BTC") -> dict[int, float]:
    """``asset``'s close-to-close return over each calendar year of the panel (A5), years by bar day: R(Y) =
    C_end(Y) / C_start(Y) - 1, with C_end(Y) the close of Y's last bar and C_start(Y) the close of the last bar of
    Y - 1, or of Y's first bar when the panel has no bar of Y - 1 (Kraken 2017: close 2017-01-02; Binance 2017:
    2017-08-18)."""
    validate_panel(panel)
    close = panel[(asset, "close")].to_numpy(dtype=float)
    years = bar_years(panel.index)
    out: dict[int, float] = {}
    for y in sorted(set(years.tolist())):
        rows = np.flatnonzero(years == y)
        before = np.flatnonzero(years == y - 1)
        start = close[before[-1]] if len(before) else close[rows[0]]
        out[int(y)] = float(close[rows[-1]] / start - 1.0)
    return out


def best_years(returns: Mapping[int, float], n: int) -> list[int]:
    """The ``n`` years with the largest return, largest first; a tie goes to the earlier year."""
    n = _count(n, "n")
    if n > len(returns) or not all(math.isfinite(r) for r in returns.values()):
        raise ValueError(f"best_years: need {n} finite yearly returns, got {dict(returns)!r}")
    return sorted(returns, key=lambda y: (-returns[y], y))[:n]


def overlaps(k: int, year: int) -> bool:
    """Window k (the months M_k .. M_(k+11), M_k = January 2017 + k months) overlaps calendar year Y when one of
    its months is in Y: 12 (Y - 2017) - 11 <= k <= 12 (Y - 2017) + 11 (A5)."""
    first = 12 * (year - 2017)
    return first - 11 <= k <= first + 11


def windows_without(windows: Iterable[int], years: Iterable[int]) -> list[int]:
    """The windows of ``windows`` that overlap none of ``years``, sorted."""
    years = tuple(years)
    return sorted(k for k in windows if not any(overlaps(k, y) for y in years))


def boom_removals(returns: Mapping[int, float]) -> list[dict]:
    """The A5 removals in order: each train year alone, then the best year and the best two years by ``returns``
    (the ranking source's yearly returns, :func:`year_returns`). Each is ``{"name", "years"}``."""
    missing = [y for y in TRAIN_YEARS if y not in returns]
    if missing:
        raise ValueError(f"boom_removals: no yearly return for {missing}")
    ranked = {y: returns[y] for y in TRAIN_YEARS}
    out = [{"name": str(y), "years": [y]} for y in TRAIN_YEARS]
    for n in (1, 2):
        best = best_years(ranked, n)
        out.append({"name": f"best {n}", "years": best})
    return out


def boom_plan(
    returns: Mapping[int, float], windows: Mapping[str, Iterable[int]], *, min_windows: int = BOOM_MIN_WINDOWS
) -> list[dict]:
    """Each A5 removal with the windows every source keeps (``windows``: the source's rolling windows in the runs
    table) and its ``status``: :data:`OK`, or :data:`MISSING` with a ``reason`` when a source keeps fewer than
    ``min_windows``."""
    min_windows = _count(min_windows, "min_windows")
    plan = []
    for removal in boom_removals(returns):
        kept = {source: windows_without(windows[source], removal["years"]) for source in SOURCES}
        short = {source: len(ks) for source, ks in kept.items() if len(ks) < min_windows}
        entry = {**removal, "windows": kept, "status": OK, "reason": None}
        if short:
            entry.update(status=MISSING, reason=f"fewer than {min_windows} windows kept: {short}")
        plan.append(entry)
    return plan


def _same(a, b):
    if (isinstance(a, str) and a == MISSING) or (isinstance(b, str) and b == MISSING):
        return MISSING
    return a == b


def boom_compare(headline: Mapping, removal: Mapping) -> dict:
    """Whether a removal's rule D output (:func:`robust`) keeps each headline value (A5): N*_rob(b) for every band,
    b*_rob for every wallet size, the app default, N_up,rob (the outcome in words), the value test and the CONFLICT
    flag. Each is True, False or :data:`MISSING` (either side MISSING); ``all`` is True only if every one is."""
    pairs = {f"N*({b:g})": (headline["N_star"][b], removal["N_star"][b]) for b in BANDS}
    pairs.update({f"b*({book:g})": (headline["b_star"][book], removal["b_star"][book]) for book in BOOKS})
    pairs["app default"] = (headline["app_default"], removal["app_default"])
    pairs["N_up"] = tuple(outcome_label(r["outcome"], r["N_up"]) for r in (headline, removal))
    pairs["value test"] = (headline["value_test"], removal["value_test"])
    pairs["CONFLICT"] = (headline["conflict"], removal["conflict"])
    same = {name: _same(a, b) for name, (a, b) in pairs.items()}
    values = list(same.values())
    same["all"] = MISSING if any(v == MISSING for v in values) else all(values)
    return same
