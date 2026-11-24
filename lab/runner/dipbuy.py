"""buy-the-dip: the owner's dip ladder, its twins, its measures and decision rules.

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the reference
rebalancer, not NautilusTrader (AGENTS.md hard rule 3). ``research/buy-the-dip/PLAN.md`` is the contract; section
numbers below are that file's. No existing file is changed: every run goes through ``protect.run_overlay``'s ``Step``
protocol (with no brake, or behind one in the tests), which hands each decision to ``portfolio._simulate`` (decided at
close t, filled at the open of t+1, costs from the ``Costs`` passed in). ``protect.index_signal``,
``protect.rolling_windows``, ``protect.boom_removals``, ``protect.windows_without``, ``protect.check_book``,
``holdmix.money_metrics`` and ``portfolio.check_targets`` are used read-only.

The rule (section 5)
--------------------
- **The index I** of the start's BTC/ETH split f is ``protect.index_signal``'s chain-linked index over the full panel.
  **The recent high** H_t is the highest I over the panel rows whose close is within 365 days before close t
  (``t - 365 days < close <= t``; :func:`recent_high`), read from the full panel.
- **Armed** at row 0. **Trigger** at the first close t* where the ladder is armed and ``I_t <= (1.0 - Y) * H_t``: it
  fixes H* = H_t*, the base B (the USDC at close t*, V_t* times the cash weight after any first buy) and the lines
  ``(1.0 - Y) * H* * (1.0 - Z) ** (k - 1)`` for k = 1 .. K, K = ``ceil(M / X - 1e-9)``, with pieces ``X * B`` (k < K)
  and ``(M - (K - 1) * X) * B`` (k = K).
- **Buys:** at each close from t* on every line not yet crossed with ``I_t <= line_k`` is crossed; the crossed pieces
  (``math.fsum``, line order) are one order, the target vector being the weights at close t plus
  ``(f, 1 - f) * amount / V_t``.
- **Re-arm** at the first close after t* where ``I_t >= H_t``; lines not crossed are dropped.
- **Caps (R1):** a buy that would put a coin above ``max_coin - h`` or cash below ``min_cash + h`` is cut to the largest
  amount that keeps both; when that leaves nothing, no order is sent and the whole amount is "capped".
- **Limit fix** (section 4): at a close where cash < min_cash or a coin > max_coin (judged at the limits with
  ``portfolio.LIMIT_TOL``), both coins are scaled by the largest lambda <= 1 that puts every coin at or below
  ``max_coin - h`` and cash at or above ``min_cash + h``. It replaces that close's buy, whose pieces are "blocked".
- **One order per close;** the decision at the last close is never filled (its crossed pieces are "not filled").

The executor (section 11)
-------------------------
:class:`BuyStep` is a ``protect.Step``: ``decide(t, w)``, ``waiting(t)`` (never: the ladder has no wait) and
``bought_back(t)`` (behind a brake: the ladder starts armed afresh). The ladder needs the wallet's USD value at each
close, which ``_simulate`` does not hand to ``decide``: the step keeps a shadow book (:class:`_Book`) that repeats
``_simulate``'s value and weight arithmetic operation for operation, and at every close the engine's weights must equal
the book's bit for bit (else :class:`ConsistencyError`). Behind a brake the step is not asked while the wallet is
stopped; the book then replays the closes it was not asked (the stop to all USDC, nothing while stopped, the buy-back
to the step's targets), and the bit-for-bit check proves the replay.

The twins (section 6) are the same step with another plan of buys: ``hold`` (none), ``dca`` (the dip run's ordered
total in 12 equal pieces, piece j at the first close at least 30 j days after close 0) and ``lump`` (the total at close
0), each with the same caps and limit fixes.

Measures (section 8) and rules (section 9)
------------------------------------------
:func:`run_measures` (one row per run), :func:`ladder_rows` (one row per ladder), :func:`compare_twins` (T_dca,
T_lump, T_hold, G), and the rules :func:`d1`, :func:`d2` and :func:`d3` over a runs table (:data:`RUN_KEYS`, ``status``
and the measures). Every percentile is ``numpy.percentile`` (linear); a pool holding a failed run gives
:data:`MISSING`. The readings pinned where the plan is loosely worded are :data:`READINGS_PINNED`.

pandas caveat (as in portfolio.py): ``attrs`` holds arrays and frames; drop them (``piece.attrs = {}``) before
``pd.concat`` or ``to_parquet``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

from lab.runner import holdmix, protect
from lab.runner.holdmix import ConsistencyError
from lab.runner.portfolio import ASSETS, LIMIT_TOL, _breach_test, _prepare, check_targets, validate_panel
from lab.runner.reference import Costs, _check_params, _real

__all__ = [
    "KINDS",
    "SETTINGS",
    "STARTS",
    "BuyStep",
    "ConsistencyError",
    "LadderPlan",
    "ScheduledPlan",
    "Setting",
    "check_events",
    "check_order_targets",
    "check_twin",
    "compare_twins",
    "d1",
    "d2",
    "d3",
    "dca_closes",
    "dip_buy",
    "dip_signal",
    "events_hash",
    "lambda_fix",
    "ladder_lines",
    "ladder_pieces",
    "ladder_rows",
    "line_count",
    "orders_hash",
    "parse_setting",
    "recent_high",
    "recompute_events",
    "run_measures",
    "setting_table",
    "start_targets",
    "window_signal",
]

# ------------------------------------------------------------------------------------------------ pinned values

DAY_US = holdmix.DAY_US
YEAR_DAYS = 365
HIGH_DAYS = 365  # the recent high's lookback (section 5): t - 365 days < close <= t
DEPOSIT = 5000.0  # D (section 4)
HEADROOM = holdmix.HEADROOM  # h = 0.02
STEADY_MIN_CASH = 0.20  # the Steady limits the plan was written for (section 4): the run refuses other values
STEADY_MAX_COIN = 0.60
Y_VALUES = (0.10, 0.20, 0.30)
Z_VALUES = (0.05, 0.10, 0.20)
X_VALUES = (0.10, 0.25)
M_VALUES = (0.25, 0.50, 1.00)
K_TOL = 1e-9  # K = ceil(M / X - 1e-9)
STARTS = tuple((s0, f) for s0 in (0.0, 0.30) for f in (0.50, 0.75))  # section 4: s0 x f
DCA_PIECES = 12
DCA_DAYS = 30
KINDS = ("hold", "dip", "dca", "lump")
TWINS = ("dca", "lump", "hold")
BUY_REASONS = ("buy", "first+buy")
REASONS = ("first", *BUY_REASONS, "limit")
CASH = (0.0, 0.0)


class Setting(NamedTuple):
    """A ladder setting (section 7): Y the first fall, Z each further fall, X each piece, M the most used per fall."""

    Y: float
    Z: float
    X: float
    M: float


SETTINGS = tuple(Setting(y, z, x, m) for y in Y_VALUES for z in Z_VALUES for x in X_VALUES for m in M_VALUES)

# Decision thresholds (section 9), fixed before any result
PERCENTILE = 90.0
DESCRIBE_PERCENTILES = (10.0, 50.0, 90.0)
TIE_TOL = 1e-12
BOOM_MIN_WINDOWS = protect.BOOM_MIN_WINDOWS  # 12
BOOM_RANK_SOURCE = "KRAKEN"

# Outcome words
MISSING = "MISSING"
NO_DEFAULT = "NO DEFAULT"
ROBUST = "ROBUST"
NOT_ROBUST = "NOT ROBUST"
OK = "ok"
LABEL = "SCOUTING, placeholder costs, train years 2017-2022, reference engine; claims no edge"

READINGS_PINNED = {
    "high_window": "H_t is the highest I over the panel rows with t - 365 days < close <= t (section 5, 'The rule "
    "(exact)'): a close exactly 365 days back does not count, one 365 days minus one microsecond back does. Section "
    "11's test list words it the other way ('a high 365 days back counts'); section 5's inequality is used",
    "floats": "trigger I_t <= (1.0 - Y) * H_t; line_k = (1.0 - Y) * H* * (1.0 - Z) ** (k - 1) (so line 1 is the "
    "trigger's float); crossing I_t <= line_k; re-arm I_t >= H_t; K = ceil(M / X - 1e-9); pieces X * B and "
    "(M - (K - 1) * X) * B; a close's amount is math.fsum of its crossed pieces in line order",
    "base": "B = V_t* * (1.0 - (w_BTC + w_ETH)), with w the weights at close t* or, at close 0, the first buy's targets "
    "(s0 f, s0 (1 - f)); V the engine's value at the close (the shadow book)",
    "order_of_checks": "At a close the running ladder first re-arms (I_t >= H_t) or crosses lines, then an armed "
    "ladder may trigger; a line can never be crossed on a re-arm close (I_t is then the year's high and the previous "
    "close is inside the year)",
    "caps": "The cut amount a is min(amount, (max_coin - h - w_BTC) / f, (max_coin - h - w_ETH) / (1 - f), (1 - "
    "min_cash - h) - (w_BTC + w_ETH)) in weight units (amount / V_t). When a cap binds and leaves a <= LIMIT_TOL "
    "(1e-9 of the wallet, portfolio's round-off allowance) no order is sent and the whole amount is capped; an "
    "amount of 0 sends nothing",
    "lambda": "lambda = min(1, (max_coin - h) / w_BTC, (max_coin - h) / w_ETH, (1 - min_cash - h) / (w_BTC + "
    "w_ETH)), each term only for a coin weight > 0; the fix's targets are (lambda w_BTC, lambda w_ETH)",
    "ordered": "'Ordered (before caps)' is the amount due at closes 0 .. n-2: sent + capped + blocked by a limit fix. "
    "Pieces crossed at the last close are 'not filled' and not ordered (a limit fix due there is never sent either). "
    "delta = ordered / B_0 with B_0 = (1 - s0) * D; the twins' total is the dip run's ordered",
    "twins": "dca-same: piece j (j = 0 .. 11) = total / 12 at the first close c with ts_c - ts_0 >= 30 j days "
    "(pieces landing on one close are summed; a piece with no such close, or at the last close, is not filled). "
    "lump-same: the total at close 0, with the first buy. 'A dip run with no order' (section 10's twin check) is one "
    "whose ordered total is 0: its twins send the first buy and limit fixes only, and equal hold bit for bit",
    "v_end": "V_end = wallet_values(ret, D)[-1] (protect: D times the run's own returns, multiplied in order); "
    "T_x = V_end / V_end(x) - 1.0; G = (V_end - V_end(dca)) / ordered, NaN when ordered is 0",
    "knife": "For each ladder with an order sent: 1.0 - min(I over the closes from its last order's fill row through "
    "the re-arm close, or the last close) / I at the open of that fill row (protect's I_open); positive is a further "
    "fall. The worst is the largest",
    "orders_filled": "A ladder order is a 'buy' or 'first+buy' order (sent at closes 0 .. n-2, so filled); 'pieces "
    "filled' counts the lines (twins: the pieces) in those orders, even when capped in part",
    "brake": "Behind a protect-gains brake (tests only): the step is not asked while stopped; at the buy-back the "
    "ladder drops any running ladder and starts armed afresh; the buy-back orders the start's targets "
    "(s0 f, s0 (1 - f))",
    "one_pass": "recompute_events finds the triggers, crossings and re-arms from I and H alone, ladder by ladder (the "
    "next trigger from the last re-arm on; each line's first crossing in [t*, re-arm)); it must equal the run's",
    "d1_missing": "D1 is MISSING when any run of its pool (every kind) failed, or a usable setting's G~ is not finite",
    "d1_active": "Active: 2 * (windows with a ladder order) >= the pool's windows (25 of 49, 21 of 41, half of a boom "
    "removal's kept windows)",
    "d1_rank": "G~ = median G over the setting's dip runs (all starts) with a ladder order; candidates within 1e-12 "
    "of the largest G~; then the larger median delta over all the setting's dip runs (exactly), the larger Y, Z, X "
    "and the smaller M",
    "d2": "NOT ROBUST when a check moves the default (naming it, and any MISSING check); else MISSING when a check or "
    "the headline is MISSING; else ROBUST. NO DEFAULT on both sides is the same default",
    "d3": "Described at the default only (NO DEFAULT and MISSING give that word). Per start and by the year of each "
    "window's first close: G over the runs with a ladder order, T_dca, T_lump and T_hold over all the runs (median, "
    "10th and 90th percentiles, share above 0); Q of each kind per start against the Steady budget as read (shown, "
    "not enforced; MISSING when the file has none); the knife's median and worst; delta and the USDC left",
}


# ------------------------------------------------------------------------------------------------ small helpers


def _days(us) -> float:
    return us / DAY_US


def _num(value, name: str, low: float, high: float, *, low_inclusive: bool, high_inclusive: bool) -> float:
    return _real(value, name, low, low_inclusive=low_inclusive, high=high, high_inclusive=high_inclusive)


def parse_setting(Y, Z, X, M) -> Setting:
    """A :class:`Setting`, strictly: Y in (0, 1), Z in [0, 1), X and M in (0, 1]."""
    return Setting(
        _num(Y, "Y", 0.0, 1.0, low_inclusive=False, high_inclusive=False),
        _num(Z, "Z", 0.0, 1.0, low_inclusive=True, high_inclusive=False),
        _num(X, "X", 0.0, 1.0, low_inclusive=False, high_inclusive=True),
        _num(M, "M", 0.0, 1.0, low_inclusive=False, high_inclusive=True),
    )


def start_targets(s0, f) -> tuple[float, float]:
    """The first buy's targets ``(s0 * f, s0 * (1.0 - f))`` (section 4); (0, 0) for an all-USDC start."""
    s0 = _num(s0, "s0", 0.0, 1.0, low_inclusive=True, high_inclusive=False)
    f = _num(f, "f", 0.0, 1.0, low_inclusive=True, high_inclusive=True)
    return (s0 * f, s0 * (1.0 - f))


def line_count(X: float, M: float) -> int:
    """K = ``ceil(M / X - 1e-9)`` (section 5)."""
    return math.ceil(M / X - K_TOL)


def ladder_lines(setting: Setting, high: float) -> list[float]:
    """The K lines ``(1.0 - Y) * H* * (1.0 - Z) ** (k - 1)``, k = 1 .. K."""
    y, z, x, m = setting
    return [(1.0 - y) * high * (1.0 - z) ** (k - 1) for k in range(1, line_count(x, m) + 1)]


def ladder_pieces(setting: Setting, base: float) -> list[float]:
    """The K pieces in USD: ``X * B`` for k < K and ``(M - (K - 1) * X) * B`` for k = K."""
    _, _, x, m = setting
    k = line_count(x, m)
    return [x * base] * (k - 1) + [(m - (k - 1) * x) * base]


def lambda_fix(w: Sequence[float], min_cash: float, max_coin: float, headroom: float = HEADROOM) -> float:
    """The limit fix's lambda (section 4; READINGS_PINNED['lambda'])."""
    terms = [1.0]
    for a in range(2):
        if w[a] > 0.0:
            terms.append((max_coin - headroom) / w[a])
    if w[0] + w[1] > 0.0:
        terms.append((1.0 - min_cash - headroom) / (w[0] + w[1]))
    return min(terms)


def _cap(w: Sequence[float], amount: float, f: float, min_cash: float, max_coin: float) -> float:
    """The largest weight a in [0, amount] keeping both coins at or below max_coin - h and cash at or above
    min_cash + h (may be negative: the wallet is already within h of a limit)."""
    rooms = [amount, (1.0 - min_cash - HEADROOM) - (w[0] + w[1])]
    if f > 0.0:
        rooms.append((max_coin - HEADROOM - w[0]) / f)
    if f < 1.0:
        rooms.append((max_coin - HEADROOM - w[1]) / (1.0 - f))
    return min(rooms)


# ------------------------------------------------------------------------------------------------ the signal

SIGNAL_COLUMNS = ("I", "I_open", "H")


def recent_high(times, index) -> np.ndarray:
    """H_t = max I_c over the rows c <= t with ``times[c] > times[t] - 365 days`` (microseconds; a monotonic deque,
    exact)."""
    ts = np.asarray(times, dtype=np.int64).tolist()
    values = np.asarray(index, dtype=float).tolist()
    if len(ts) != len(values) or not ts:
        raise ValueError("recent_high: times and index must be non-empty and of one length")
    if any(b <= a for a, b in zip(ts, ts[1:], strict=False)):
        raise ValueError("recent_high: times must be strictly increasing")
    span = HIGH_DAYS * DAY_US
    out = [0.0] * len(ts)
    queue: list[int] = []
    head = 0
    for t, now in enumerate(ts):
        while len(queue) > head and values[queue[-1]] <= values[t]:
            queue.pop()
        head = min(head, len(queue))
        queue.append(t)
        while ts[queue[head]] <= now - span:
            head += 1
        out[t] = values[queue[head]]
    return np.asarray(out, dtype=float)


def dip_signal(panel: pd.DataFrame, f) -> pd.DataFrame:
    """The index of the start's split f over a whole panel: ``I`` and ``I_open`` from ``protect.index_signal`` and
    ``H``, the 365-day high (:func:`recent_high`), on the panel's index. Computed once per source and f."""
    sig = protect.index_signal(panel, f)
    high = recent_high(panel.index.asi8, sig["I"].to_numpy(dtype=float))
    return pd.DataFrame({"I": sig["I"], "I_open": sig["I_open"], "H": high}, index=panel.index, dtype=float)


def window_signal(signal: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """The rows of a whole-panel :func:`dip_signal` at a window's closes, refused unless every close is there."""
    _check_signal(signal)
    idx = pd.DatetimeIndex(index)
    missing = idx.difference(signal.index)
    if len(missing):
        raise ValueError(f"the signal has no row for {len(missing)} closes, e.g. {missing[0].isoformat()}")
    return signal.loc[idx]


def _check_signal(signal) -> None:
    if not isinstance(signal, pd.DataFrame) or tuple(signal.columns) != SIGNAL_COLUMNS:
        raise ValueError(f"signal must be a DataFrame with columns {SIGNAL_COLUMNS} (dip_signal)")


def _signal_arrays(signal, bars: pd.DataFrame) -> tuple[list[float], list[float], list[float]]:
    _check_signal(signal)
    if not signal.index.equals(bars.index):
        raise ValueError("signal must be on exactly the bars' index (window_signal)")
    i_close = signal["I"].to_numpy(dtype=float)
    high = signal["H"].to_numpy(dtype=float)
    i_open = signal["I_open"].to_numpy(dtype=float)
    if not (np.isfinite(i_close).all() and (i_close > 0).all()):
        raise ValueError("signal I must be finite and > 0 at every close")
    if not (np.isfinite(high).all() and (high >= i_close).all()):
        raise ValueError("signal H must be finite and at least I at every close")
    if not (np.isfinite(i_open[1:]).all() and (i_open[1:] > 0).all()):
        raise ValueError("signal I_open must be finite and > 0 at every open after row 0")
    return i_close.tolist(), high.tolist(), i_open.tolist()


# ------------------------------------------------------------------------------------------------ the book


class _Book:
    """``portfolio._simulate``'s value and weight arithmetic, operation for operation, so the step knows V_t."""

    def __init__(self, o: Sequence[Sequence[float]], c: Sequence[Sequence[float]], costs: Costs):
        self.o, self.c, self.costs = o, c, costs
        self.t = 0
        self.w = [0.0, 0.0]
        self.value = costs.capital_usd

    def advance(self, target: Sequence[float] | None) -> None:
        """From close t to t + 1, with ``target`` the order sent at close t (None: no order)."""
        o, c, costs, w = self.o, self.c, self.costs, self.w
        t = self.t + 1
        m = 2
        g = [o[a][t] / c[a][t - 1] - 1.0 for a in range(m)]
        wg = 0.0
        for a in range(m):
            wg += w[a] * g[a]
        drift = 1.0 + wg
        traded = [0.0] * m
        if target is not None:
            drifted = [w[a] * (1.0 + g[a]) / drift for a in range(m)]
            traded = [abs(target[a] - drifted[a]) for a in range(m)]
        total = 0.0
        for a in range(m):
            total += traded[a]
        if total > 0.0:
            h = [c[a][t] / o[a][t] - 1.0 for a in range(m)]
            v_open = self.value * drift
            gas = costs.gas_fraction(v_open)
            k = 0.0
            for a in range(m):
                if traded[a] > 0.0:
                    k += traded[a] * costs.rate(traded[a] * v_open) + gas
            th = 0.0
            for a in range(m):
                th += target[a] * h[a]
            ride = 1.0 + th
            growth = drift * (1.0 - k) * ride
            self.w = [target[a] * (1.0 + h[a]) / ride for a in range(m)]
        else:
            r = [c[a][t] / c[a][t - 1] - 1.0 for a in range(m)]
            wr = 0.0
            for a in range(m):
                wr += w[a] * r[a]
            growth = 1.0 + wr
            self.w = [w[a] * (1.0 + r[a]) / growth for a in range(m)]
        self.value *= growth
        self.t = t


# ------------------------------------------------------------------------------------------------ the plans


class LadderPlan:
    """The dip ladder's state machine (section 5): ``due(t, base, v)`` returns the USD amount due at close t and the
    crossed lines; ``reset(t)`` drops a running ladder and arms afresh (behind a brake, at a buy-back)."""

    def __init__(self, setting: Setting, i_close: Sequence[float], high: Sequence[float]):
        self.setting = setting
        self.i, self.h = i_close, high
        self.k = line_count(setting.X, setting.M)
        self.armed = True
        self.current: dict | None = None
        self.ladders: list[dict] = []

    def reset(self, t: int) -> None:
        if self.current is not None:
            self.current["dropped"] = t
        self.current, self.armed = None, True

    def due(self, t: int, base: Sequence[float], v: float) -> tuple[float, int, list[int]]:
        i, hi = self.i[t], self.h[t]
        lad, crossed = self.current, []
        if lad is not None:
            if i >= hi:
                lad["rearm"] = t
                self.current, self.armed, lad = None, True, None
            else:
                crossed = [k for k in range(self.k) if lad["crossed"][k] is None and i <= lad["lines"][k]]
        if self.armed and i <= (1.0 - self.setting.Y) * hi:
            b = v * (1.0 - (base[0] + base[1]))
            lad = {
                "id": len(self.ladders),
                "start": t,
                "high": hi,
                "base": b,
                "lines": ladder_lines(self.setting, hi),
                "pieces": ladder_pieces(self.setting, b),
                "crossed": [None] * self.k,
                "rearm": None,
                "dropped": None,
            }
            self.ladders.append(lad)
            self.current, self.armed = lad, False
            crossed = [k for k in range(self.k) if i <= lad["lines"][k]]
        if not crossed:
            return 0.0, -1 if lad is None else lad["id"], []
        for k in crossed:
            lad["crossed"][k] = t
        return math.fsum(lad["pieces"][k] for k in crossed), lad["id"], crossed


class ScheduledPlan:
    """A twin's buys: fixed USD pieces due at given closes (``amounts``: close -> the pieces due there)."""

    def __init__(self, amounts: Mapping[int, Sequence[float]]):
        self.amounts = {c: list(p) for c, p in amounts.items()}
        self.ladders: list[dict] = []

    def reset(self, t: int) -> None:
        return None

    def due(self, t: int, base: Sequence[float], v: float) -> tuple[float, int, list[int]]:
        pieces = self.amounts.get(t, [])
        return math.fsum(pieces), -1, list(range(len(pieces)))


def dca_closes(times) -> list[int | None]:
    """Piece j's close (j = 0 .. 11): the first row c with ``ts_c - ts_0 >= 30 * j`` days; None when there is none."""
    ts = np.asarray(times, dtype=np.int64)
    out: list[int | None] = []
    for j in range(DCA_PIECES):
        rows = np.flatnonzero(ts - ts[0] >= DCA_DAYS * j * DAY_US)
        out.append(int(rows[0]) if len(rows) else None)
    return out


def _scheduled(kind: str, total: float, times) -> tuple[dict[int, list[float]], float]:
    """The twin's pieces by close and the USD of pieces with no close in the window (READINGS_PINNED['twins'])."""
    if kind == "hold" or total == 0.0:
        return {}, 0.0
    if kind == "lump":
        return {0: [total]}, 0.0
    piece = total / DCA_PIECES
    by_close: dict[int, list[float]] = {}
    lost = []
    for c in dca_closes(times):
        if c is None:
            lost.append(piece)
        else:
            by_close.setdefault(c, []).append(piece)
    return by_close, math.fsum(lost)


# ------------------------------------------------------------------------------------------------ the step


BUY_COLUMNS = ("close", "ladder", "lines", "due", "sent", "capped", "blocked", "unfilled", "reason")


class BuyStep:
    """The ladder (or a twin) as a ``protect.Step`` (module docstring). ``targets`` is the start's first buy (also what
    a brake's buy-back orders); ``plan`` a :class:`LadderPlan` or :class:`ScheduledPlan`."""

    def __init__(
        self,
        plan: LadderPlan | ScheduledPlan,
        start: tuple[float, float],
        f: float,
        limits: Mapping,
        costs: Costs,
        o: Sequence[Sequence[float]],
        c: Sequence[Sequence[float]],
    ):
        self.plan = plan
        self.targets = start
        self.first = start[0] > 0.0 or start[1] > 0.0
        self.f = f
        self.min_cash, self.max_coin = limits["min_cash"], limits["max_coin"]
        self.breached = _breach_test(self.min_cash, self.max_coin)
        self.book = _Book(o, c, costs)
        self.last = len(o[0]) - 1
        self.reason_at: dict[int, str] = {}
        self.in_wait_at: dict[int, bool] = {}
        self.held: list[int] = []
        self.sent: dict[int, tuple[float, float] | None] = {}
        self.values = [math.nan] * (self.last + 1)
        self.values[0] = costs.capital_usd
        self.asked: list[int] = []
        self.bought: list[int] = []
        self.inferred_stops: list[int] = []
        self.stopped = False
        self.buys: list[tuple] = []

    # ---- the shadow book
    def _sync(self, t: int) -> None:
        """Bring the book to close t; closes the step was not asked are the brake's (a stop, then nothing)."""
        while self.book.t < t:
            u = self.book.t
            if u in self.sent:
                target = self.sent[u]
            elif not self.stopped:
                target = CASH
                self.stopped = True
                self.inferred_stops.append(u)
            else:
                target = None
            self.book.advance(target)
            self.values[self.book.t] = self.book.value

    def waiting(self, t: int) -> bool:
        return False

    def bought_back(self, t: int) -> None:
        self._sync(t)
        self.bought.append(t)
        self.sent[t] = self.targets
        self.stopped = False
        self.plan.reset(t)

    def decide(self, t: int, w: tuple[float, ...]) -> tuple[float, float] | None:
        self._sync(t)
        if list(w) != self.book.w:
            raise ConsistencyError(
                f"close {t}: the engine's weights {tuple(w)} are not the step's book {tuple(self.book.w)}"
            )
        self.asked.append(t)
        out = self._decide(t, w, self.book.value)
        self.sent[t] = out
        if out is not None:
            try:
                check_targets(
                    out[0], out[1], min_cash=self.min_cash, max_coin=self.max_coin, headroom=HEADROOM
                )
            except ValueError as exc:  # R1: every order's targets pass check_targets
                raise ConsistencyError(f"close {t}: the order's targets fail check_targets: {exc}") from exc
            self.in_wait_at[t] = False
        return out

    def _record(self, t: int, ladder: int, lines: int, due: float, reason: str, **parts) -> None:
        row = dict.fromkeys(("sent", "capped", "blocked", "unfilled"), 0.0)
        row.update(parts)
        self.buys.append(
            (t, ladder, lines, due, row["sent"], row["capped"], row["blocked"], row["unfilled"], reason)
        )

    def _decide(self, t: int, w: tuple[float, ...], v: float) -> tuple[float, float] | None:
        first = t == 0 and self.first
        base = self.targets if t == 0 else (w[0], w[1])
        due, ladder, crossed = self.plan.due(t, base, v)
        if t == self.last:
            if due > 0.0:
                self._record(t, ladder, len(crossed), due, "", unfilled=due)
            return None
        if t > 0 and self.breached(w):
            lam = lambda_fix(w, self.min_cash, self.max_coin)
            self.reason_at[t] = "limit"
            if due > 0.0:
                self._record(t, ladder, len(crossed), due, "limit", blocked=due)
            return (lam * w[0], lam * w[1])
        if due > 0.0:
            want = due / v
            a = _cap(base, want, self.f, self.min_cash, self.max_coin)
            if a < want and a <= LIMIT_TOL:
                reason = "first" if first else ""
                self._record(t, ladder, len(crossed), due, reason, capped=due)
                if first:
                    self.reason_at[t] = reason
                    return base
                return None
            sent = due if a == want else a * v
            reason = self.reason_at[t] = "first+buy" if first else "buy"
            self._record(t, ladder, len(crossed), due, reason, sent=sent, capped=due - sent)
            return (base[0] + self.f * a, base[1] + (1.0 - self.f) * a)
        if first:
            self.reason_at[t] = "first"
            return base
        return None


# ------------------------------------------------------------------------------------------------ the run


_PARAMS = frozenset({"kind", "Y", "Z", "X", "M", "s0", "f", "min_cash", "max_coin", "total"})


def _parse(params) -> dict:
    p = _check_params("dip_buy", params, _PARAMS)
    kind = p.get("kind")
    if kind not in KINDS:
        raise ValueError(f"dip_buy: kind must be one of {KINDS}, got {kind!r}")
    ladder = [k for k in ("Y", "Z", "X", "M") if p.get(k) is not None]
    if kind == "dip":
        if len(ladder) != 4:
            raise ValueError("dip_buy: a dip run needs Y, Z, X and M")
        setting = parse_setting(p["Y"], p["Z"], p["X"], p["M"])
    elif ladder:
        raise ValueError(f"dip_buy: a {kind} run takes no {ladder}")
    else:
        setting = None
    total = p.get("total")
    if kind in ("dca", "lump"):
        total = _real(total, "total", 0.0, low_inclusive=True)
    elif total is not None:
        raise ValueError(f"dip_buy: a {kind} run takes no total")
    limits = {}
    for key in ("min_cash", "max_coin"):
        limits[key] = _num(p.get(key), key, 0.0, 1.0, low_inclusive=True, high_inclusive=True)
    s0 = _num(p.get("s0"), "s0", 0.0, 1.0, low_inclusive=True, high_inclusive=False)
    f = _num(p.get("f"), "f", 0.0, 1.0, low_inclusive=True, high_inclusive=True)
    start = start_targets(s0, f)
    check_targets(*start, min_cash=limits["min_cash"], max_coin=limits["max_coin"], headroom=HEADROOM)
    return {
        "kind": kind,
        "setting": setting,
        "total": total,
        "limits": limits,
        "s0": s0,
        "f": f,
        "start": start,
    }


def make_step(p: Mapping, bars: pd.DataFrame, costs: Costs, signal: pd.DataFrame | None):
    """A factory of fresh :class:`BuyStep` objects for parsed params ``p`` (one per pass of ``run_overlay``)."""
    o = [bars[(a, "open")].to_numpy(dtype=float).tolist() for a in ASSETS]
    c = [bars[(a, "close")].to_numpy(dtype=float).tolist() for a in ASSETS]
    if p["kind"] == "dip":
        if signal is None:
            raise ValueError("dip_buy: a dip run needs the signal (dip_signal, window_signal)")
        i_close, high, _ = _signal_arrays(signal, bars)

        def plan():
            return LadderPlan(p["setting"], i_close, high)

    else:
        amounts, _ = _scheduled(p["kind"], p["total"], bars.index.asi8)

        def plan():
            return ScheduledPlan(amounts)

    def make() -> BuyStep:
        return BuyStep(plan(), p["start"], p["f"], p["limits"], costs, o, c)

    return make


def dip_buy(
    params: Mapping,
    bars: pd.DataFrame,
    costs: Costs | None = None,
    signal: pd.DataFrame | None = None,
    brake: protect.Brake | None = None,
    brake_signal: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One run (a dip run or a twin), through ``protect.run_overlay`` (module docstring). ``params``: ``kind`` (one
    of :data:`KINDS`), ``s0``, ``f``, ``min_cash``, ``max_coin`` (the Steady limits as read), ``Y``, ``Z``, ``X``,
    ``M`` (dip runs) or ``total`` (dca and lump twins, USD). ``signal``: the window's rows of :func:`dip_signal` (dip
    runs). ``brake`` and ``brake_signal`` (``protect.index_signal`` rows) put a protect-gains brake on top (tests).

    The result is ``run_overlay``'s (``reasons``, ``order_targets``, ...) with ``kind``, ``setting``, ``start``,
    ``f``, ``total``, ``limits``, ``buys`` (one row per close with an amount due, :data:`BUY_COLUMNS`), ``ladders``,
    ``book_values`` (V at each close the step reached), ``asked``, ``bought_back`` and ``lost`` (twin pieces with no
    close) in ``attrs``."""
    p = _parse(params)
    validate_panel(bars)
    costs = _prepare(bars, costs)
    factory = make_step(p, bars, costs, signal)
    steps: list[BuyStep] = []

    def make() -> BuyStep:
        steps.append(factory())
        return steps[-1]

    result = protect.run_overlay(bars, costs, make, brake, brake_signal)
    step = steps[-1]
    _, lost = _scheduled(p["kind"], p["total"], bars.index.asi8) if p["kind"] != "dip" else ({}, 0.0)
    result.attrs.update(
        kind=p["kind"],
        setting=None if p["setting"] is None else dict(p["setting"]._asdict()),
        start=(p["s0"], p["f"]),
        f=p["f"],
        total=p["total"],
        limits=dict(p["limits"]),
        buys=pd.DataFrame(step.buys, columns=list(BUY_COLUMNS)),
        ladders=[_ladder_record(lad) for lad in step.plan.ladders],
        book_values=np.asarray(step.values, dtype=float),
        asked=np.asarray(step.asked, dtype=np.int64),
        bought_back=np.asarray(step.bought, dtype=np.int64),
        lost=lost,
    )
    return result


def _ladder_record(lad: Mapping) -> dict:
    return {
        "id": lad["id"],
        "start": lad["start"],
        "high": lad["high"],
        "base": lad["base"],
        "lines": list(lad["lines"]),
        "pieces": list(lad["pieces"]),
        "crossed": [None if c is None else int(c) for c in lad["crossed"]],
        "rearm": lad["rearm"],
        "dropped": lad["dropped"],
    }


# ------------------------------------------------------------------------------------------------ the checks


def recompute_events(i_close: Sequence[float], high: Sequence[float], setting: Setting) -> dict:
    """Section 10's one-pass recompute from I and H alone (READINGS_PINNED['one_pass']): ``triggers`` (t*, H*),
    ``crossings`` ((ladder, k, close), k from 1) and ``rearms`` (closes)."""
    i = np.asarray(i_close, dtype=float)
    hi = np.asarray(high, dtype=float)
    n = len(i)
    out: dict[str, list] = {"triggers": [], "crossings": [], "rearms": []}
    start = 0
    while True:  # start is 0 or a re-arm close, always < n
        fires = np.flatnonzero(i[start:] <= (1.0 - setting.Y) * hi[start:])
        if not len(fires):
            break
        t = start + int(fires[0])
        ladder = len(out["triggers"])
        out["triggers"].append((t, float(hi[t])))
        ups = np.flatnonzero(i[t + 1 :] >= hi[t + 1 :])
        end = t + 1 + int(ups[0]) if len(ups) else n
        for k, line in enumerate(ladder_lines(setting, float(hi[t])), start=1):
            hits = np.flatnonzero(i[t:end] <= line)
            if len(hits):
                out["crossings"].append((ladder, k, t + int(hits[0])))
        if end == n:
            break
        out["rearms"].append(end)
        start = end
    out["crossings"].sort(key=lambda x: (x[0], x[2], x[1]))
    return out


def run_events(result: pd.DataFrame) -> dict:
    """The triggers, crossings and re-arms of a dip run, from its ladders (same shape as :func:`recompute_events`)."""
    out: dict[str, list] = {"triggers": [], "crossings": [], "rearms": []}
    for lad in result.attrs["ladders"]:
        out["triggers"].append((lad["start"], lad["high"]))
        for k, c in enumerate(lad["crossed"], start=1):
            if c is not None:
                out["crossings"].append((lad["id"], k, c))
        if lad["rearm"] is not None:
            out["rearms"].append(lad["rearm"])
    out["crossings"].sort(key=lambda x: (x[0], x[2], x[1]))
    return out


def check_events(result: pd.DataFrame, signal: pd.DataFrame) -> None:
    """:class:`ConsistencyError` unless a dip run's triggers, crossings and re-arms equal :func:`recompute_events`'s
    (section 10)."""
    i_close, high, _ = _signal_arrays(signal, result)
    setting = Setting(**result.attrs["setting"])
    again = recompute_events(i_close, high, setting)
    mine = run_events(result)
    for key in ("triggers", "crossings", "rearms"):
        if mine[key] != again[key]:
            raise ConsistencyError(
                f"the run's {key} {mine[key]} differ from the one-pass recompute's {again[key]}"
            )


def check_order_targets(result: pd.DataFrame, limits: Mapping) -> None:
    """R1 (section 10): every order's targets pass ``portfolio.check_targets`` with the limits and h = 0.02, and every
    order has a known reason (one 'first' or 'first+buy' at close 0 when the start holds crypto)."""
    targets = np.asarray(result.attrs["order_targets"], dtype=float).reshape(-1, 2)
    reasons = [str(r) for r in result.attrs["reasons"]]
    orders = np.asarray(result.attrs["orders"], dtype=np.int64).tolist()
    if len(targets) != len(orders) or len(reasons) != len(orders) or not set(reasons) <= set(REASONS):
        raise ConsistencyError("orders, reasons and targets are not aligned, or a reason is unknown")
    for t, r, w in zip(orders, reasons, targets.tolist(), strict=True):
        if r.startswith("first") != (t == 0 and result.attrs["start"][0] > 0.0):
            raise ConsistencyError(
                f"the order at close {t} has reason {r}: the first buy is the close-0 order only"
            )
        try:
            check_targets(
                w[0], w[1], min_cash=limits["min_cash"], max_coin=limits["max_coin"], headroom=HEADROOM
            )
        except ValueError as exc:
            raise ConsistencyError(f"the order at close {t} ({r}) fails check_targets: {exc}") from exc


def check_twin(twin: pd.DataFrame, total: float, hold: pd.DataFrame | None = None) -> None:
    """Section 10: a twin's ordered total (with any piece not filled) equals its dip run's ``total`` to 1e-12; with
    ``total`` 0 the twin equals ``hold`` bit for bit (every column, orders, reasons, targets and fills)."""
    buys = twin.attrs["buys"]
    got = math.fsum(buys["due"].tolist()) + twin.attrs["lost"]
    if abs(got - total) > 1e-12 * abs(total):
        raise ConsistencyError(
            f"the {twin.attrs['kind']} twin's total {got!r} is not its dip run's {total!r}"
        )
    if total == 0.0 and hold is not None:
        for col in hold.columns:
            if twin[col].to_numpy(dtype="<f8").tobytes() != hold[col].to_numpy(dtype="<f8").tobytes():
                raise ConsistencyError(f"a twin of a run with no order differs from hold in {col}")
        same = (
            np.asarray(twin.attrs["orders"]).tolist() == np.asarray(hold.attrs["orders"]).tolist()
            and [str(r) for r in twin.attrs["reasons"]] == [str(r) for r in hold.attrs["reasons"]]
            and np.asarray(twin.attrs["order_targets"]).tobytes()
            == np.asarray(hold.attrs["order_targets"]).tobytes()
            and twin.attrs["fills"].equals(hold.attrs["fills"])
        )
        if not same:
            raise ConsistencyError("a twin of a run with no order differs from hold in its orders or fills")


def check_values(result: pd.DataFrame, tol: float = 1e-12) -> None:
    """The step's book values against V from the run's own returns (:func:`protect.wallet_values`), relative."""
    v = protect.wallet_values(result["ret"].to_numpy(dtype=float), result.attrs["book_values"][0])
    book = np.asarray(result.attrs["book_values"], dtype=float)
    seen = np.isfinite(book)
    if (np.abs(book[seen] / v[seen] - 1.0) > tol).any():
        raise ConsistencyError("the step's book values differ from the run's own returns")


def _digest(parts: Mapping) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def events_hash(result: pd.DataFrame) -> str:
    """SHA-256 of a dip run's triggers (closes), crossings and re-arms: what must not depend on costs (section 10)."""
    ev = run_events(result)
    return _digest(
        {
            "triggers": [t for t, _ in ev["triggers"]],
            "crossings": [list(x) for x in ev["crossings"]],
            "rearms": ev["rearms"],
        }
    )


def orders_hash(result: pd.DataFrame) -> str:
    """SHA-256 of the order closes and reasons (a description: caps and limit fixes may move them with costs)."""
    return _digest(
        {
            "orders": np.asarray(result.attrs["orders"], dtype=np.int64).tolist(),
            "reasons": [str(r) for r in result.attrs["reasons"]],
        }
    )


# ------------------------------------------------------------------------------------------------ measures


RUN_MEASURES = (
    "F",
    "v_end",
    "total_return",
    "ladders",
    "ladders_filled",
    "orders",
    "pieces",
    "first_order_days",
    "ordered_usd",
    "sent_usd",
    "capped_usd",
    "blocked_usd",
    "unfilled_usd",
    "unfilled_lines",
    "delta",
    "limit_fixes",
    "usdc_left",
    "knife_worst",
    "fees_pct_per_year",
    "gas_pct_per_year",
    "first_cost_pct",
)
LADDER_COLUMNS = (
    "ladder",
    "start",
    "start_ts",
    "high",
    "base",
    "lines",
    "crossed",
    "orders",
    "first_order",
    "last_order",
    "rearm",
    "rearm_ts",
    "knife",
)


def run_measures(result: pd.DataFrame, costs: Costs, signal: pd.DataFrame | None = None) -> dict:
    """Section 8's per-run measures (:data:`RUN_MEASURES`; the twins' comparisons are :func:`compare_twins`). The
    knife needs the window's ``signal`` (dip runs); without it ``knife_worst`` is NaN."""
    money = holdmix.money_metrics(result, costs)
    a = result.attrs
    ret = result["ret"].to_numpy(dtype=float)
    position = result["position"].to_numpy(dtype=float)
    times = result.index.asi8
    v = protect.wallet_values(ret, costs.capital_usd)
    buys = a["buys"]
    n = len(result)
    sent_rows = buys[buys["sent"].to_numpy() > 0.0]
    before = buys[buys["close"].to_numpy() < n - 1]
    ordered = math.fsum(before["due"].tolist())
    reasons = [str(r) for r in a["reasons"]]
    orders = np.asarray(a["orders"], dtype=np.int64).tolist()
    buy_orders = [t for t, r in zip(orders, reasons, strict=True) if r in BUY_REASONS]
    knives = [row["knife"] for row in ladder_rows(result, signal) if math.isfinite(row["knife"])]
    b0 = (1.0 - a["start"][0]) * costs.capital_usd
    return {
        "F": 0.0 - money["max_drawdown"],  # 0.0, never -0.0, for a wallet that never falls
        "v_end": float(v[-1]),
        "total_return": money["total_return"],
        "ladders": len(a["ladders"]),
        "ladders_filled": len({int(x) for x in sent_rows["ladder"].tolist() if x >= 0}),
        "orders": len(buy_orders),
        "pieces": int(sent_rows["lines"].sum()),
        "first_order_days": _days(int(times[buy_orders[0]] - times[0])) if buy_orders else math.nan,
        "ordered_usd": ordered,
        "sent_usd": math.fsum(buys["sent"].tolist()),
        "capped_usd": math.fsum(buys["capped"].tolist()),
        "blocked_usd": math.fsum(buys["blocked"].tolist()),
        "unfilled_usd": math.fsum(buys["unfilled"].tolist()) + a["lost"],
        "unfilled_lines": int(buys.loc[buys["unfilled"].to_numpy() > 0.0, "lines"].sum()),
        "delta": ordered / b0,
        "limit_fixes": reasons.count("limit"),
        "usdc_left": 1.0 - float(position[-1]),
        "knife_worst": max(knives) if knives else math.nan,
        "fees_pct_per_year": money["fees_pct_per_year"],
        "gas_pct_per_year": money["gas_pct_per_year"],
        "first_cost_pct": money["first_cost_pct"],
    }


def ladder_rows(result: pd.DataFrame, signal: pd.DataFrame | None) -> list[dict]:
    """One row per ladder (:data:`LADDER_COLUMNS`): its start, H*, B, lines, crossings, the orders it sent, its
    re-arm and the falling knife (READINGS_PINNED['knife']; NaN without an order or without ``signal``)."""
    a = result.attrs
    buys = a["buys"]
    n = len(result)
    index = result.index
    arrays = None if signal is None else _signal_arrays(signal, result)
    out = []
    for lad in a["ladders"]:
        mine = buys[(buys["ladder"].to_numpy() == lad["id"]) & (buys["sent"].to_numpy() > 0.0)]
        sent = mine["close"].astype(int).tolist()
        knife = math.nan
        if sent and arrays is not None:
            i_close, _, i_open = arrays
            u = sent[-1] + 1
            end = lad["rearm"] if lad["rearm"] is not None else n - 1
            knife = 1.0 - min(i_close[u : end + 1]) / i_open[u]
        out.append(
            {
                "ladder": lad["id"],
                "start": lad["start"],
                "start_ts": index[lad["start"]],
                "high": lad["high"],
                "base": lad["base"],
                "lines": len(lad["lines"]),
                "crossed": sum(c is not None for c in lad["crossed"]),
                "orders": len(sent),
                "first_order": sent[0] if sent else -1,
                "last_order": sent[-1] if sent else -1,
                "rearm": -1 if lad["rearm"] is None else lad["rearm"],
                "rearm_ts": pd.NaT if lad["rearm"] is None else index[lad["rearm"]],
                "knife": knife,
            }
        )
    return out


def compare_twins(dip: Mapping, dca: Mapping, lump: Mapping, hold: Mapping) -> dict:
    """T_dca, T_lump, T_hold and G of a dip run (section 8) from the measures of the four runs."""
    v = dip["v_end"]
    ordered = dip["ordered_usd"]
    return {
        "T_dca": v / dca["v_end"] - 1.0,
        "T_lump": v / lump["v_end"] - 1.0,
        "T_hold": v / hold["v_end"] - 1.0,
        "G": (v - dca["v_end"]) / ordered if ordered > 0.0 else math.nan,
    }


# ------------------------------------------------------------------------------------------------ the rules

RUN_KEYS = ("source", "cost", "kind", "Y", "Z", "X", "M", "s0", "f", "window")
SETTING_KEYS = ("Y", "Z", "X", "M")


def _pct(values, q: float = PERCENTILE) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def _failed(frame: pd.DataFrame) -> bool:
    return bool((frame["status"].to_numpy() != OK).any())


def _of(frame: pd.DataFrame, **equal) -> pd.DataFrame:
    mask = np.ones(len(frame), dtype=bool)
    for col, value in equal.items():
        mask &= frame[col].to_numpy() == value
    return frame[mask]


def _settings(frame: pd.DataFrame) -> list[Setting]:
    rows = zip(*(frame[k].tolist() for k in SETTING_KEYS), strict=True)
    return sorted({Setting(*map(float, r)) for r in rows})


def _starts(frame: pd.DataFrame) -> list[tuple[float, float]]:
    return sorted(set(zip(frame["s0"].tolist(), frame["f"].tolist(), strict=True)))


def _key(setting: Setting | str):
    return setting if isinstance(setting, str) else tuple(setting)


def d1(pool: pd.DataFrame) -> dict:
    """D1, the default setting on one pool (one source and cost, any windows; section 9). ``default`` is a
    :class:`Setting` as a tuple (Y, Z, X, M), :data:`NO_DEFAULT` or :data:`MISSING`; ``table`` holds each (setting,
    start)'s numbers and ``settings`` each setting's usable flag, G~ and median delta."""
    out = {"default": MISSING, "windows": None, "table": [], "settings": [], "candidates": [], "reason": None}
    dips = pool[pool["kind"].to_numpy() == "dip"]
    dcas = pool[pool["kind"].to_numpy() == "dca"]
    if dips.empty or dcas.empty:
        out["reason"] = "no dip or dca runs in the pool"
        return out
    if _failed(pool):
        out["reason"] = "a run in the pool failed (stop rule 4)"
        return out
    windows = sorted(set(dips["window"].tolist()))
    starts = _starts(dips)
    n = len(windows)
    out["windows"] = n
    for setting in _settings(dips):
        at = dict(zip(SETTING_KEYS, setting, strict=True))
        mine = _of(dips, **at)
        usable = True
        for s0, f in starts:
            d, c = _of(mine, s0=s0, f=f), _of(dcas, **at, s0=s0, f=f)
            if sorted(d["window"].tolist()) != windows or sorted(c["window"].tolist()) != windows:
                raise ValueError(f"d1: setting {setting} at start {(s0, f)} does not hold one run per window")
            active_n = int((d["orders"].to_numpy() >= 1).sum())
            q, q_dca = _pct(d["F"]), _pct(c["F"])
            worst, worst_dca = float(d["F"].max()), float(c["F"].max())
            active = 2 * active_n >= n
            ok = active and q <= q_dca and worst <= worst_dca
            usable = usable and ok
            out["table"].append(
                {
                    **at,
                    "s0": s0,
                    "f": f,
                    "runs": len(d),
                    "active_windows": active_n,
                    "active": bool(active),
                    "Q": q,
                    "Q_dca": q_dca,
                    "worst_F": worst,
                    "worst_F_dca": worst_dca,
                    "Q_pass": bool(q <= q_dca),
                    "worst_pass": bool(worst <= worst_dca),
                    "pass": bool(ok),
                }
            )
        with_order = mine[mine["orders"].to_numpy() >= 1]
        g = with_order["G"].to_numpy(dtype=float)
        out["settings"].append(
            {
                **at,
                "usable": bool(usable),
                "runs_with_order": len(with_order),
                "G_med": float(np.median(g)) if len(g) else math.nan,
                "delta_med": float(np.median(mine["delta"].to_numpy(dtype=float))),
            }
        )
    usable = [s for s in out["settings"] if s["usable"]]
    if not usable:
        out.update(default=NO_DEFAULT, reason="no usable setting")
        return out
    if not all(math.isfinite(s["G_med"]) for s in usable):
        out["reason"] = "a usable setting's G~ is not finite"
        return out
    best = max(s["G_med"] for s in usable)
    candidates = [s for s in usable if abs(s["G_med"] - best) <= TIE_TOL]
    pick = max(candidates, key=lambda s: (s["delta_med"], s["Y"], s["Z"], s["X"], -s["M"]))
    out.update(
        default=tuple(pick[k] for k in SETTING_KEYS),
        candidates=[tuple(s[k] for k in SETTING_KEYS) for s in candidates],
    )
    return out


def d2(headline: Mapping, checks: Mapping[str, Mapping | None]) -> dict:
    """D2's robustness label (section 9; protect D4's rules): each check is a :func:`d1` output, or None (MISSING,
    e.g. a boom removal leaving fewer than 12 windows)."""
    mine = _key(headline["default"])
    per, moved, missing = {}, [], []
    for name, check in checks.items():
        if check is None:
            per[name] = MISSING
            missing.append(name)
            continue
        theirs = per[name] = _key(check["default"])
        if theirs == MISSING:
            missing.append(name)
        elif theirs != mine:
            moved.append(name)
    if mine == MISSING:
        label = f"{MISSING} (headline)"
    elif moved:
        label = f"{NOT_ROBUST} ({', '.join(moved + [f'{m}: MISSING' for m in missing])})"
    elif missing:
        label = f"{MISSING} ({', '.join(missing)})"
    else:
        label = ROBUST
    return {"default": mine, "label": label, "checks": per, "moved": moved, "missing": missing}


def _describe(values) -> dict:
    x = np.asarray(values, dtype=float)
    if not len(x):
        return {"n": 0, "p10": None, "median": None, "p90": None, "share_above_0": None}
    p10, med, p90 = (float(v) for v in np.percentile(x, DESCRIBE_PERCENTILES))
    return {"n": len(x), "p10": p10, "median": med, "p90": p90, "share_above_0": float((x > 0.0).mean())}


def _describe_runs(dips: pd.DataFrame) -> dict:
    with_order = dips[dips["orders"].to_numpy() >= 1]
    return {
        "G": _describe(with_order["G"]),
        "T_dca": _describe(dips["T_dca"]),
        "T_lump": _describe(dips["T_lump"]),
        "T_hold": _describe(dips["T_hold"]),
    }


def d3(pool: pd.DataFrame, ladders: pd.DataFrame, default, budget: float | None) -> dict:
    """D3, the description printed with the default (section 9; READINGS_PINNED['d3']). ``pool`` holds a ``year``
    column (the year of each window's first close); ``ladders`` one row per ladder with ``run_id`` and ``knife``."""
    if isinstance(default, str):
        return {"status": default}
    if _failed(pool):
        return {"status": MISSING, "reason": "a run in the pool failed (stop rule 4)"}
    at = dict(zip(SETTING_KEYS, default, strict=True))
    dips = _of(pool[pool["kind"].to_numpy() == "dip"], **at)
    out = {"status": OK, "setting": at, "budget": MISSING if budget is None else budget, "per_start": []}
    for s0, f in _starts(dips):
        d = _of(dips, s0=s0, f=f)
        qs = {"Q": _pct(d["F"])}
        for kind in TWINS:
            twin = pool[pool["kind"].to_numpy() == kind]
            twin = _of(twin, s0=s0, f=f) if kind == "hold" else _of(twin, **at, s0=s0, f=f)
            qs[f"Q_{kind}"] = _pct(twin["F"])
        knife = ladders[ladders["run_id"].isin(d["run_id"]).to_numpy()]["knife"].to_numpy(dtype=float)
        knife = knife[np.isfinite(knife)]
        out["per_start"].append(
            {
                "s0": s0,
                "f": f,
                **_describe_runs(d),
                "by_year": {int(y): _describe_runs(_of(d, year=y)) for y in sorted(set(d["year"].tolist()))},
                **qs,
                "above_budget": None if budget is None else {k: bool(v > budget) for k, v in qs.items()},
                "knife_median": float(np.median(knife)) if len(knife) else None,
                "knife_worst": float(knife.max()) if len(knife) else None,
                "delta_median": float(np.median(d["delta"])),
                "usdc_left_median": float(np.median(d["usdc_left"])),
            }
        )
    knife = ladders[ladders["run_id"].isin(dips["run_id"]).to_numpy()]["knife"].to_numpy(dtype=float)
    knife = knife[np.isfinite(knife)]
    out["knife_median"] = float(np.median(knife)) if len(knife) else None
    out["knife_worst"] = float(knife.max()) if len(knife) else None
    return out


def setting_table(pool: pd.DataFrame) -> list[dict]:
    """The full table per setting and start (section 14), on one pool: runs, failed, the medians of G (runs with a
    ladder order), T_dca, T_lump, T_hold, delta, the USDC left, orders and ladders, the share of windows with an
    order, the worst knife and the median fees a year."""
    out = []
    dips = pool[pool["kind"].to_numpy() == "dip"]
    for setting in _settings(dips):
        at = dict(zip(SETTING_KEYS, setting, strict=True))
        for s0, f in _starts(dips):
            d = _of(dips, **at, s0=s0, f=f)
            ok = d[d["status"].to_numpy() == OK]
            entry = {**at, "s0": s0, "f": f, "runs": len(d), "failed": int(len(d) - len(ok))}
            if not ok.empty:
                g = ok[ok["orders"].to_numpy() >= 1]["G"].to_numpy(dtype=float)
                knife = ok["knife_worst"].to_numpy(dtype=float)
                entry.update(
                    {
                        "active_share": float((ok["orders"].to_numpy() >= 1).mean()),
                        "G_med": float(np.median(g)) if len(g) else None,
                        **{
                            f"{k}_med": float(np.median(ok[k].to_numpy(dtype=float)))
                            for k in ("T_dca", "T_lump", "T_hold", "delta", "usdc_left", "fees_pct_per_year")
                        },
                        "orders_med": float(np.median(ok["orders"])),
                        "ladders_med": float(np.median(ok["ladders"])),
                        "knife_worst": float(np.nanmax(knife)) if np.isfinite(knife).any() else None,
                    }
                )
            out.append(entry)
    return out
