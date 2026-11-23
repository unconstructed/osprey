"""protect-gains: the "protect my gains" brake on top of the "hold this mix" tool, its measures and decision rules.

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the reference
rebalancer, not NautilusTrader (AGENTS.md hard rule 3). ``research/protect-gains/PLAN.md`` is the contract; section
numbers below are that file's. No existing file is changed: every run hands a ``decide`` callback to
``portfolio._simulate`` (decided at close t, filled at the open of t+1, costs from the ``Costs`` passed in), and
``holdmix.py`` is used read-only (``_hold_params``, ``money_metrics``, ``window_slice``, ``best_years``, ...).

The tool copy (section 9, review B6)
------------------------------------
:class:`ToolStep` is a copy of ``holdmix.hold_mix``'s decision steps (first buy, limit fix, the wait, the relative
band, the reset), as an object an overlay drives: ``decide(t, w)`` is hold_mix's ``decide`` closure statement for
statement, ``waiting(t)`` says whether the tool's wait runs at close t, and ``bought_back(t)`` restarts the tool's
clocks at a buy-back. With the brake off, :func:`protect` equals ``hold_mix`` bit for bit (``ret``, weights, orders,
reasons, ``in_wait``, ``held``; :func:`check_tool_copy`).

The overlay (sections 5 and 10)
-------------------------------
:func:`run_overlay` wraps a generic decision step (:class:`Step`: the tool copy, or a toy dip buyer in the tests). At
each close, in this order: while the wallet is stopped the inner step is not called; a due buy-back orders the step's
``targets`` and tells the step (``bought_back``); a stop close orders all USDC (the brake wins: one order per close);
otherwise the inner step decides. The brake (:class:`Brake`):

- **Line A** (X): fires at close t when ``V_t <= (1.0 - X) * H_t``. **Line B** (Y, with the activation gain g of
  :data:`B_GAIN`): active when ``H_t >= (1.0 + g) * D``; fires when active and ``V_t <= D + Y * (H_t - D)``. A value
  exactly on a line fires. V_t is the wallet's value at close t (:func:`wallet_values`); D the deposit
  (``costs.capital_usd``, 5,000 USD in the study); H_t the highest V over rows 1..t, and after a buy-back ordered at
  close c over rows c+1..t.
- **Buy-backs** (decided at a close c, filled at the open of c+1; intervals in calendar days from the sale's fill
  instant, close t's timestamp): ``rebound`` at the first close at least 7 days on with ``I_c >= (1.0 + r) * I_t``;
  ``trend`` at the first Monday close at least 7 days on with ``I_c > 1.02 * SMA200_c``, once I has closed at or below
  ``1.02 * SMA200`` at some close after the fill instant (R2); ``wait`` at the first close at least D days on.
- **Readings** (R4): ``separate``: the tool's wait never holds a buy-back back; ``counts``: a due buy-back waits until
  the tool's wait has run out (W = 15 days after the tool's last counted trade), then orders.

Stops are found **by re-running** (:func:`run_overlay`, as ``trend.stop_events`` does): run with the stops found so
far, find the next stop on that run's V (:func:`next_stop`), add it, run again. Buy-backs need no V, so each pass
decides them itself. :func:`recompute_events` finds the same stops and buy-backs in one pass over a run's own ``ret``
(section 9's check); :func:`check_orders` checks the order sequence and the tool's wait; :func:`check_book` replays
the fills in coin units and USDC cash.

The index (section 5)
---------------------
:func:`index_signal`: I = 1 at the panel's first row, ``I_c = I_{c-1} * (1.0 + f * r_BTC + (1.0 - f) * r_ETH)``
(close-to-close returns), SMA200 by ``trend.sma`` (NaN before row 199), and I at each open (for the missed rebound),
``I_open_u = I_{u-1} * (1.0 + f * g_BTC + (1.0 - f) * g_ETH)`` with g = open_u / close_{u-1} - 1. Computed once per
source and f over the full panel; each window's run takes its rows.

Measures (section 7) and rules (section 8)
------------------------------------------
:func:`stop_rows` (one row per filled stop) and :func:`run_measures` (one row per run) read the result and the fill
log, never re-simulating. The rules :func:`d1` .. :func:`d6` are pure functions over a runs table (one row per run with
the key columns of :data:`RUN_KEYS`, ``status`` and the measures) and a stops table; every percentile is
``numpy.percentile`` (linear), and a pool holding a failed run gives :data:`MISSING`.

Pinned readings where the plan is loosely worded (each fixed before any result; :data:`READINGS_PINNED`)
---------------------------------------------------------------------------------------------------------
See :data:`READINGS_PINNED` (the study script records it in its start record).

pandas caveat (as in portfolio.py): ``attrs`` holds arrays and frames; drop them (``piece.attrs = {}``) before
``pd.concat`` or ``to_parquet``.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import NamedTuple, Protocol

import numpy as np
import pandas as pd

from lab.runner import holdmix
from lab.runner.holdmix import ConsistencyError
from lab.runner.portfolio import ASSETS, WEIGHT_COLUMNS, _breach_test, _prepare, _simulate, validate_panel
from lab.runner.reference import Costs, _check_params, _real
from lab.runner.trend import sma

__all__ = [
    "AUTO_MODES",
    "B_GAIN",
    "LEVELS",
    "LINES",
    "MIXES",
    "MODES",
    "READINGS",
    "Brake",
    "ConsistencyError",
    "Step",
    "ToolStep",
    "boom_removals",
    "check_book",
    "check_orders",
    "check_tool_copy",
    "cost_vs_reference",
    "d1",
    "d2",
    "d3",
    "d4",
    "d5",
    "d6",
    "defaults",
    "index_signal",
    "level_table",
    "line_fires",
    "line_value",
    "next_stop",
    "overlaps",
    "parse_brake",
    "protect",
    "recompute_events",
    "rolling_windows",
    "run_measures",
    "run_overlay",
    "signal_rows",
    "stop_rows",
    "tool_params",
    "wallet_values",
    "windows_without",
]

# ------------------------------------------------------------------------------------------------ pinned values

DAY_US = holdmix.DAY_US
YEAR_DAYS = 365
HEADROOM = holdmix.HEADROOM  # 0.02 (section 4)
DEPOSIT = 5000.0  # D (section 4): the study's costs.capital_usd
TOOL_BAND = 0.30  # the owner's default band (section 4)
TOOL_CAP = 2  # the owner's default cap: a 15-day wait
TOOL_WAIT = holdmix.wait_days(TOOL_CAP)
MIXES = tuple((s, f) for s in (0.30, 0.50, 0.70) for f in (0.50, 0.75))  # section 4
LINES = ("A", "B")
LEVELS = {"A": (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40), "B": (0.40, 0.50, 0.60, 0.70, 0.80)}
# R3: line B's activation gain g = 0.10 / (0.90 - Y), pinned as values (1/3 as 1.0 / 3.0), never computed
B_GAIN = {0.40: 0.20, 0.50: 0.25, 0.60: 1.0 / 3.0, 0.70: 0.50, 0.80: 1.00}
MODES = ("rebound-5", "rebound0", "rebound+5", "trend", "wait30", "wait180")
MODE_SPECS = {
    "rebound-5": ("rebound", -0.05),
    "rebound0": ("rebound", 0.0),
    "rebound+5": ("rebound", 0.05),
    "trend": ("trend", math.nan),
    "wait30": ("wait", 30.0),
    "wait180": ("wait", 180.0),
}
AUTO_MODES = ("rebound-5", "rebound0", "rebound+5", "trend")
WAIT_MODE = "wait30"  # stands for an attentive customer (D2); wait180 decides nothing
D2_TIE_ORDER = ("trend", "rebound+5", "rebound0", "rebound-5")
READINGS = ("separate", "counts")
IN_FORCE = "counts"  # D6: "counts" until the owner approves "separate" in writing
MIN_DAYS = 7  # the automatic buy-backs' minimum, from the sale's fill instant
TREND_LOOKBACK = 200
TREND_BAND = 1.02
MONDAY = 0  # Monday 00:00 UTC (the bar of Sunday)
FIRST_SIGNAL_ROW = TREND_LOOKBACK - 1  # row 199
RESTOP_DAYS = 30
CASH = (0.0, 0.0)
TOOL_REASONS = ("first", "limit", "band", "reset")
BRAKE_REASONS = ("stop", "buyback")
WAIT_STARTS = ("limit", "band", "reset", "buyback")  # orders that (re)start the tool's wait

# Decision thresholds (section 8), fixed before any result
PERCENTILE = 90.0
PROTECT_LEFT = 3.0  # meaningful protection: 3 * Q <= 2 * Q0
PROTECT_RIGHT = 2.0
RESTOP_MAX = 0.25
TIE_TOL = 1e-12
PROMISE_PERCENTILE = 95.0
BOOM_MIN_WINDOWS = 12

# Windows (section 6): 24 months, closes from the 2nd of M_k to the 1st of M_(k+24)
WINDOW_MONTHS = 24
N_WINDOWS = 49  # k = 0..48: the last window ends 2023-01-01
TRAIN_YEARS = holdmix.TRAIN_YEARS
BOOM_RANK_SOURCE = "KRAKEN"

# Outcome words
MISSING = "MISSING"
NO_DEFAULT = "NO DEFAULT"
NONE = "none"
ROBUST = "ROBUST"
NOT_ROBUST = "NOT ROBUST"
OK = "ok"
WAIT = "wait"  # D2's default buy-back when it is the customer's own (wait-30's numbers)
LABEL = "SCOUTING, placeholder costs, train years 2017-2022, reference engine; claims no edge"

READINGS_PINNED = {
    "V": "V_t = D * prod(1 + ret[1..t]), the run's own returns multiplied in order from D (np.cumprod), so the "
    "re-running and the one-pass recompute read the same floats",
    "fill_instant": "The fill instant of an order decided at close t is close t's timestamp; every interval is "
    "calendar days between close timestamps (microseconds), so a missing close never shifts a count",
    "line_floats": "Line A fires when V <= (1.0 - X) * H; line B is active when H >= (1.0 + g) * D and fires when "
    "V <= D + Y * (H - D); g from the pinned table B_GAIN (1/3 as 1.0 / 3.0), never from the formula",
    "index_floats": "I_c = I_{c-1} * (1.0 + f * r_BTC + (1.0 - f) * r_ETH) in Python floats, row by row; the trend "
    "signal is I_c > 1.02 * SMA_c and a dip I_c <= 1.02 * SMA_c; rebound I_c >= (1.0 + r) * I_t",
    "no_sma": "A close without an SMA200 (row < 199 of the source's panel) is neither a trend signal nor a dip",
    "dip": "R2's dip is a close strictly after the sale's order close (its fill instant) and before the signal "
    "close; it may fall inside the 7-day minimum",
    "due": "Under 'counts' a buy-back that is due while the tool's wait runs is held (listed in buyback_held) and "
    "ordered at the first close the wait has run out, without re-checking its signal",
    "wait_restart": "Under both readings the buy-back restarts the tool's wait and its reset clock (section 5, "
    "'After a buy-back': as after a limit fix); 'separate' never holds it back, 'counts' does. The sale never "
    "touches the tool's clocks",
    "in_wait": "in_wait is True for a limit fix or a 'separate' buy-back sent while the tool's wait runs; False for "
    "every other order (the wait holds band, reset and 'counts' buy-backs; the sale is never a trade back to the mix)",
    "last_close": "A line crossed at the last close is listed in 'unfilled' (not re-run, no order); a buy-back due "
    "at the last close is never sent, so the stop is 'not bought back'",
    "missed_rebound": "I's return from the open of the sale's fill row to the open of the buy-back's fill row, with I "
    "at an open chain-linked from the previous close (index_signal's I_open); not bought back: to the last close",
    "overshoot_before_cost": "(line - V_open) / line, V_open = V_t * (1.0 + (w_BTC g_BTC + w_ETH g_ETH)), the "
    "engine's value at the fill's open before its costs",
    "restop": "A buy-back is a re-stop when the next filled stop's order close is at most 30 days (inclusive) after "
    "the buy-back's fill instant; a buy-back with no later stop is not one. Share = re-stops / filled buy-backs",
    "usdc_time": "Days from the sale's fill instant to the buy-back's (or to the last close when not bought back); "
    "usdc_share divides their sum by the window's span in days",
    "b_kept_end": "For a run where B was active at some close: (V_end - D) / (P - D), P the highest V over rows 1..n-1",
    "b_below_d": "A B sale is below D when V_sale < D; its depth is V_sale / D - 1 (the worst is the most negative)",
    "fees_split": "Legs on rows >= 2 are the brake's when the order's reason is stop or buyback, the tool's otherwise "
    "(limit, band, reset); the first buy is reported apart, as in holdmix.money_metrics",
    "c_tie": "D2, D3 and D6 compare (C~, then C-) with D1's tie: C~ values within 1e-12 are equal, then C- exactly",
    "d2_missing": "D2 is MISSING when the D1 of any automatic mode or of wait-30 is MISSING",
    "d3_missing": "D3 is MISSING when either line type's D2 is MISSING",
    "d6": "D6 is MISSING when any D2 is MISSING; 'separate' is recommended only when at least one line type has a "
    "default under both readings and every such type gives a strictly smaller (C~, C-) under 'separate'. The "
    "reading in force is 'counts' whatever D6 recommends (no written approval exists before the run)",
    "stage2_reading": "Stage 2 runs the reading in force (D6's 'counts'): the defaults reported are that reading's, "
    "and D4's labels are printed next to them",
    "d4_label": "NOT ROBUST when any check moves a default (naming it, and any MISSING check); else MISSING when any "
    "check, or the headline itself, is MISSING; else ROBUST. NO DEFAULT (or none, for D3) on both sides is the same",
    "d5_b": "D5's B worst sale below D is 'none' when no B stop sold below D (with stops, it is not MISSING)",
}


# ------------------------------------------------------------------------------------------------ small helpers


def _count(value, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def _is_word(value, word: str) -> bool:
    return isinstance(value, str) and value == word


def _days(us) -> float:
    return us / DAY_US


def wallet_values(ret, deposit: float) -> np.ndarray:
    """V at every close: ``V_0 = deposit`` and ``V_t = V_{t-1} * (1.0 + ret[t])`` (``np.cumprod``, in order)."""
    r = np.asarray(ret, dtype=float)
    if r.ndim != 1 or not len(r) or not np.isfinite(r).all():
        raise ValueError("ret must be a non-empty 1-D array of finite returns")
    d = _real(deposit, "deposit", 0.0, low_inclusive=False)
    return np.cumprod(np.concatenate(([d], 1.0 + r[1:])))


# ------------------------------------------------------------------------------------------------ the brake


class Brake(NamedTuple):
    """A brake setting (section 5)."""

    line: str  # "A" or "B"
    level: float  # X (A) or Y (B)
    gain: float  # B's activation gain g (NaN for A)
    mode: str  # one of MODES
    kind: str  # "rebound", "trend" or "wait"
    point: float  # r (rebound), D in days (wait), NaN (trend)
    reading: str  # "separate" or "counts"

    def record(self) -> dict:
        return {
            "line": self.line,
            "level": self.level,
            "gain": None if math.isnan(self.gain) else self.gain,
            "mode": self.mode,
            "reading": self.reading,
        }


def parse_brake(line, level, mode, reading) -> Brake:
    """A :class:`Brake` from its four settings, strictly: ``line`` "A" (``level`` X in (0, 1)) or "B" (``level`` Y,
    one of :data:`B_GAIN`'s values), ``mode`` one of :data:`MODES`, ``reading`` one of :data:`READINGS`."""
    if line not in LINES:
        raise ValueError(f"line must be one of {LINES}, got {line!r}")
    if line == "A":
        level = _real(level, "level", 0.0, low_inclusive=False, high=1.0)
        gain = math.nan
    else:
        if isinstance(level, bool) or not isinstance(level, numbers.Real) or float(level) not in B_GAIN:
            raise ValueError(
                f"line B's level must be one of {tuple(B_GAIN)} (its gain is pinned), got {level!r}"
            )
        level = float(level)
        gain = B_GAIN[level]
    if mode not in MODE_SPECS:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if reading not in READINGS:
        raise ValueError(f"reading must be one of {READINGS}, got {reading!r}")
    kind, point = MODE_SPECS[mode]
    return Brake(line, level, gain, mode, kind, point, reading)


def line_value(brake: Brake, high: float, deposit: float) -> float:
    """The line at a high H: A ``(1.0 - X) * H``; B ``D + Y * (H - D)`` when active (``H >= (1.0 + g) * D``), else
    NaN."""
    if brake.line == "A":
        return (1.0 - brake.level) * high
    if high >= (1.0 + brake.gain) * deposit:
        return deposit + brake.level * (high - deposit)
    return math.nan


def line_fires(brake: Brake, value: float, high: float, deposit: float) -> bool:
    """The line's test at one close (section 5): A ``V <= (1.0 - X) * H``; B active and ``V <= D + Y * (H - D)``."""
    if brake.line == "A":
        return value <= (1.0 - brake.level) * high
    return high >= (1.0 + brake.gain) * deposit and value <= deposit + brake.level * (high - deposit)


def next_stop(values, start: int, brake: Brake, deposit: float) -> int | None:
    """The first close t >= ``start`` where the line fires, with H the running maximum of ``values`` from ``start``
    (the restart row: 1, or c+1 after a buy-back ordered at c); None when it never fires."""
    v = np.asarray(values, dtype=float)
    start = _count(start, "start", 1)
    if start >= len(v):
        return None
    seg = v[start:]
    high = np.maximum.accumulate(seg)
    if brake.line == "A":
        hit = seg <= (1.0 - brake.level) * high
    else:
        hit = (high >= (1.0 + brake.gain) * deposit) & (seg <= deposit + brake.level * (high - deposit))
    rows = np.flatnonzero(hit)
    return start + int(rows[0]) if len(rows) else None


# ------------------------------------------------------------------------------------------------ the index


SIGNAL_COLUMNS = ("I", "I_open", "sma")


def index_signal(panel: pd.DataFrame, f) -> pd.DataFrame:
    """The chain-linked index of a mix's crypto (BTC share ``f``) over a whole panel (module docstring): columns
    ``I`` (1 at row 0), ``I_open`` (I at each open; NaN at row 0) and ``sma`` (SMA200 of I by ``trend.sma``; NaN
    before row 199), on the panel's index."""
    validate_panel(panel)
    f = _real(f, "f", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    cb, ce = (panel[(a, "close")].to_numpy(dtype=float).tolist() for a in ASSETS)
    ob, oe = (panel[(a, "open")].to_numpy(dtype=float).tolist() for a in ASSETS)
    n = len(cb)
    close, opened = [1.0] * n, [math.nan] * n
    for c in range(1, n):
        rb, re_ = cb[c] / cb[c - 1] - 1.0, ce[c] / ce[c - 1] - 1.0
        gb, ge = ob[c] / cb[c - 1] - 1.0, oe[c] / ce[c - 1] - 1.0
        opened[c] = close[c - 1] * (1.0 + f * gb + (1.0 - f) * ge)
        close[c] = close[c - 1] * (1.0 + f * rb + (1.0 - f) * re_)
    average = sma(close, TREND_LOOKBACK)
    return pd.DataFrame({"I": close, "I_open": opened, "sma": average}, index=panel.index, dtype=float)


def signal_rows(signal: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """The rows of a whole-panel :func:`index_signal` at the closes of ``index`` (a window), refused
    (``ValueError``) unless every close is there."""
    _check_signal_frame(signal)
    idx = pd.DatetimeIndex(index)
    missing = idx.difference(signal.index)
    if len(missing):
        raise ValueError(f"the signal has no row for {len(missing)} closes, e.g. {missing[0].isoformat()}")
    return signal.loc[idx]


def _check_signal_frame(signal) -> None:
    if not isinstance(signal, pd.DataFrame) or tuple(signal.columns) != SIGNAL_COLUMNS:
        raise ValueError(f"signal must be a DataFrame with columns {SIGNAL_COLUMNS} (index_signal)")


def _signal_arrays(signal, bars: pd.DataFrame) -> tuple[list, list, list]:
    _check_signal_frame(signal)
    if not signal.index.equals(bars.index):
        raise ValueError("signal must be on exactly the bars' index (signal_rows)")
    i_close = signal["I"].to_numpy(dtype=float)
    i_open = signal["I_open"].to_numpy(dtype=float)
    avg = signal["sma"].to_numpy(dtype=float)
    if not (np.isfinite(i_close).all() and (i_close > 0).all()):
        raise ValueError("signal I must be finite and > 0 at every close")
    if not (np.isfinite(i_open[1:]).all() and (i_open[1:] > 0).all()):
        raise ValueError("signal I_open must be finite and > 0 at every open after row 0")
    if not ((np.isnan(avg) | (avg > 0)).all() and not np.isinf(avg).any()):
        raise ValueError("signal sma must be NaN (no average yet) or finite and > 0")
    return i_close.tolist(), i_open.tolist(), avg.tolist()


def _is_dip(c: int, i_close: Sequence[float], avg: Sequence[float]) -> bool:
    return not math.isnan(avg[c]) and i_close[c] <= TREND_BAND * avg[c]


def _buyback_signal(
    brake: Brake,
    c: int,
    sale: int,
    times: Sequence[int],
    i_close: Sequence[float],
    avg: Sequence[float],
    monday: Sequence[bool],
    dipped: bool,
) -> bool:
    """Whether the buy-back of a stop ordered at close ``sale`` is due at close ``c`` (section 5)."""
    elapsed = times[c] - times[sale]
    if brake.kind == "wait":
        return elapsed >= brake.point * DAY_US
    if elapsed < MIN_DAYS * DAY_US:
        return False
    if brake.kind == "rebound":
        return i_close[c] >= (1.0 + brake.point) * i_close[sale]
    return dipped and monday[c] and not math.isnan(avg[c]) and i_close[c] > TREND_BAND * avg[c]


# ------------------------------------------------------------------------------------------------ the inner steps


class Step(Protocol):
    """A decision step the overlay drives (the tool copy, or a toy dip buyer in the tests). Besides these attributes it
    has ``decide(t, w)``: an order (a target vector) or None at close t, only called while the wallet holds the mix;
    ``waiting(t)``: the step's wait runs at close t (the 'counts' reading holds a due buy-back while it does); and
    ``bought_back(t)``: the overlay ordered a buy-back at close t.

    ``targets``: the vector a buy-back orders; ``reason_at`` and ``in_wait_at``: the reason and in-wait flag of each
    order the step sent, by close; ``held``: closes where the step's wait held an order back."""

    targets: tuple[float, float]
    reason_at: dict[int, str]
    in_wait_at: dict[int, bool]
    held: list[int]


class ToolStep:
    """The "hold this mix" decision steps, a copy of ``holdmix.hold_mix``'s ``decide`` (section 9, review B6).

    ``p`` is ``holdmix._hold_params``'s dict; ``times`` the panel's close times in microseconds. ``decide`` is
    hold_mix's closure statement for statement; ``bought_back(t)`` restarts both clocks at a buy-back ordered at close
    t (section 5: as after a limit fix)."""

    def __init__(self, p: Mapping, times: Sequence[int]):
        self.targets = p["targets"]
        self.times = list(times)
        self.last = len(self.times) - 1
        self.wait_us = p["wait"] * DAY_US
        self.reset_us = None if p["reset"] is None else p["reset"] * DAY_US
        self.coins = [
            (a, target, p["band"] * target) for a, target in enumerate(self.targets) if target > 0.0
        ]
        self.breached = _breach_test(p["min_cash"], p["max_coin"])
        self.first_buy_waits = p["first_buy_waits"]
        self.reason_at: dict[int, str] = {}
        self.in_wait_at: dict[int, bool] = {}
        self.held: list[int] = []
        self.clock: dict[str, int | None] = {"any": None, "wait": None}

    def waiting(self, t: int) -> bool:
        return self.clock["wait"] is not None and self.times[t] - self.clock["wait"] < self.wait_us

    def decide(self, t: int, w: tuple[float, ...]) -> tuple[float, ...] | None:
        clock = self.clock
        now = self.times[t]
        waiting = clock["wait"] is not None and now - clock["wait"] < self.wait_us
        if t == 0:
            reason = "first"
        elif self.breached(w):
            reason = "limit"
        elif any(abs(w[a] - target) > limit for a, target, limit in self.coins):
            reason = "band"
        elif self.reset_us is not None and now - clock["any"] >= self.reset_us:
            reason = "reset"
        else:
            return None
        if waiting and reason != "limit":
            if t < self.last:
                self.held.append(t)
            return None
        self.reason_at[t] = reason
        self.in_wait_at[t] = waiting
        clock["any"] = now
        if reason != "first" or self.first_buy_waits:
            clock["wait"] = now
        return self.targets

    def bought_back(self, t: int) -> None:
        now = self.times[t]
        self.clock["any"] = now
        self.clock["wait"] = now


_TOOL_KEYS = frozenset(
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
_BRAKE_KEYS = frozenset({"line", "level", "mode", "reading"})


def tool_params(
    targets, limits: Mapping, *, band: float = TOOL_BAND, wait: int = TOOL_WAIT, reset=None
) -> dict:
    """``hold_mix``'s params at the owner's default (section 4): band 0.30, a 15-day wait, no reset, the Steady
    limits as read (``limits``: ``portfolio.risk_limits("steady")``) and h = 0.02."""
    return {
        "w_btc": float(targets[0]),
        "w_eth": float(targets[1]),
        "band": float(band),
        "wait_days": int(wait),
        "min_cash": limits["min_cash"],
        "max_coin": limits["max_coin"],
        "headroom": HEADROOM,
        "reset_days": reset,
        "first_buy_waits": False,
    }


def _parse(params) -> tuple[dict, Brake | None]:
    p = _check_params("protect", params, _TOOL_KEYS | _BRAKE_KEYS)
    tool = holdmix._hold_params({k: v for k, v in p.items() if k in _TOOL_KEYS})
    given = sorted(k for k in _BRAKE_KEYS if p.get(k) is not None)
    if p.get("line") is None:
        if given:
            raise ValueError(f"protect: {given} given without a line (the brake is off without 'line')")
        return tool, None
    missing = sorted(_BRAKE_KEYS - set(given))
    if missing:
        raise ValueError(f"protect: a brake needs {sorted(_BRAKE_KEYS)}; missing {missing}")
    return tool, parse_brake(p["line"], p["level"], p["mode"], p["reading"])


# ------------------------------------------------------------------------------------------------ the overlay


def _pass(
    bars: pd.DataFrame,
    costs: Costs,
    step: Step,
    brake: Brake | None,
    arrays: tuple | None,
    stops: Sequence[int],
) -> tuple[pd.DataFrame, dict]:
    """One run of the overlay with the stops ``stops`` known (each in an armed stretch of this run)."""
    times = bars.index.asi8.tolist()
    last = len(times) - 1
    monday = (bars.index.day_of_week.to_numpy() == MONDAY).tolist()
    i_close, _, avg = arrays if arrays is not None else ([], [], [])
    stop_at = set(stops)
    own: dict[int, str] = {}
    own_wait: dict[int, bool] = {}
    sent: dict[int, tuple[float, ...]] = {}
    trace = {"buybacks": [], "due": [], "held": [], "stops_seen": []}
    state = {"stopped": False, "sale": -1, "dipped": False, "due": None}

    def decide(t: int, w: tuple[float, ...]) -> tuple[float, ...] | None:
        out = _decide(t, w)
        if out is not None:
            sent[t] = out
        return out

    def _decide(t: int, w: tuple[float, ...]) -> tuple[float, ...] | None:
        if state["stopped"]:
            if state["due"] is None:
                if _buyback_signal(brake, t, state["sale"], times, i_close, avg, monday, state["dipped"]):
                    state["due"] = t
                elif brake.kind == "trend" and _is_dip(t, i_close, avg):
                    state["dipped"] = True
            if state["due"] is None or t == last:
                return None
            exempt = brake.reading == "separate"
            if not exempt and step.waiting(t):
                trace["held"].append(t)
                return None
            own[t] = "buyback"
            own_wait[t] = exempt and step.waiting(t)
            step.bought_back(t)
            trace["buybacks"].append(t)
            trace["due"].append(state["due"])
            state.update(stopped=False, sale=-1, dipped=False, due=None)
            return step.targets
        if t in stop_at:
            own[t] = "stop"
            own_wait[t] = False
            trace["stops_seen"].append(t)
            state.update(stopped=True, sale=t, dipped=False, due=None)
            return CASH
        return step.decide(t, w)

    result = _simulate(bars, costs, decide)
    if sorted(trace["stops_seen"]) != sorted(stop_at):
        raise ConsistencyError(
            f"a known stop {sorted(stop_at)} fell while the wallet was stopped in a re-run"
        )
    orders = result.attrs["orders"].tolist()
    result.attrs["reasons"] = np.asarray(
        [own[t] if t in own else step.reason_at[t] for t in orders], dtype=object
    )
    result.attrs["in_wait"] = np.asarray(
        [own_wait[t] if t in own else step.in_wait_at[t] for t in orders], dtype=bool
    )
    result.attrs["held"] = np.asarray(step.held, dtype=np.int64)
    result.attrs["order_targets"] = np.asarray([sent[t] for t in orders], dtype=float).reshape(len(orders), 2)
    return result, trace


def run_overlay(
    bars: pd.DataFrame,
    costs: Costs | None,
    make_step: Callable[[], Step],
    brake: Brake | None = None,
    signal: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """The overlay on a fresh inner step (``make_step()`` per pass), through ``portfolio._simulate`` (module
    docstring). ``brake=None`` runs the inner step alone. Returns the last pass's result with ``_simulate``'s attrs
    plus ``reasons``, ``in_wait``, ``held`` (the inner step's), ``order_targets``, and with a brake: ``brake`` (its
    record), ``deposit`` (D), ``stops`` (filled stops' order closes), ``unfilled`` (a line crossed at the last close),
    ``buybacks``, ``buyback_due`` (the close each became due), ``buyback_held`` (closes a 'counts' buy-back was held,
    1..n-2), ``not_bought_back`` (the last stop has no buy-back) and ``passes``."""
    costs = _prepare(bars, costs)
    if brake is None:
        result, _ = _pass(bars, costs, make_step(), None, None, ())
        result.attrs["brake"] = None
        return result
    if signal is None:
        raise ValueError("run_overlay: a brake needs the index signal (index_signal, signal_rows)")
    arrays = _signal_arrays(signal, bars)
    deposit = costs.capital_usd
    n = len(bars)
    stops: list[int] = []
    unfilled: list[int] = []
    passes = 0
    while True:
        result, trace = _pass(bars, costs, make_step(), brake, arrays, stops)
        passes += 1
        if not stops:
            start = 1
        else:
            after = [c for c in trace["buybacks"] if c > stops[-1]]
            start = after[0] + 1 if after else n
        values = wallet_values(result["ret"].to_numpy(dtype=float), deposit)
        nxt = next_stop(values, start, brake, deposit) if start < n else None
        if nxt is None:
            break
        if nxt == n - 1:
            unfilled.append(nxt)
            break
        stops.append(nxt)
    result.attrs["brake"] = brake.record()
    result.attrs["deposit"] = deposit
    result.attrs["stops"] = np.asarray(stops, dtype=np.int64)
    result.attrs["unfilled"] = np.asarray(unfilled, dtype=np.int64)
    result.attrs["buybacks"] = np.asarray(trace["buybacks"], dtype=np.int64)
    result.attrs["buyback_due"] = np.asarray(trace["due"], dtype=np.int64)
    result.attrs["buyback_held"] = np.asarray(trace["held"], dtype=np.int64)
    result.attrs["not_bought_back"] = len(stops) > len(trace["buybacks"])
    result.attrs["passes"] = passes
    return result


def protect(
    params: Mapping, bars: pd.DataFrame, costs: Costs | None = None, signal: pd.DataFrame | None = None
) -> pd.DataFrame:
    """The study's run: the tool copy (``hold_mix``'s params) with the brake on top when ``params`` holds ``line``,
    ``level``, ``mode`` and ``reading`` (all four, or none: the reference R). ``signal``: the window's rows of
    :func:`index_signal` (needed with a brake)."""
    tool, brake = _parse(params)
    validate_panel(bars)
    times = bars.index.asi8.tolist()
    result = run_overlay(bars, costs, lambda: ToolStep(tool, times), brake, signal)
    result.attrs["wait_days"] = tool["wait"]
    return result


# ------------------------------------------------------------------------------------------------ the checks


def check_tool_copy(copy: pd.DataFrame, original: pd.DataFrame) -> None:
    """Section 9: with the brake off the copy equals ``hold_mix`` bit for bit: the index, every column, ``orders``,
    ``reasons``, ``in_wait``, ``held``, ``trade_returns``, ``n_trades`` and the fill log; else
    :class:`ConsistencyError`."""
    if not copy.index.equals(original.index) or list(copy.columns) != list(original.columns):
        raise ConsistencyError("the tool copy's result has another index or other columns than hold_mix's")
    for col in original.columns:
        if copy[col].to_numpy(dtype="<f8").tobytes() != original[col].to_numpy(dtype="<f8").tobytes():
            raise ConsistencyError(f"the tool copy's {col} differs from hold_mix's")
    for key in ("orders", "trade_returns", "in_wait", "held"):
        if np.asarray(copy.attrs[key]).tobytes() != np.asarray(original.attrs[key]).tobytes():
            raise ConsistencyError(f"the tool copy's {key} differs from hold_mix's")
    if [str(r) for r in copy.attrs["reasons"]] != [str(r) for r in original.attrs["reasons"]]:
        raise ConsistencyError("the tool copy's reasons differ from hold_mix's")
    if copy.attrs["n_trades"] != original.attrs["n_trades"] or not copy.attrs["fills"].equals(
        original.attrs["fills"]
    ):
        raise ConsistencyError("the tool copy's fills differ from hold_mix's")


def _armed_restarts(buybacks: Iterable[int]) -> list[int]:
    return [1, *(int(c) + 1 for c in buybacks)]


def recompute_events(
    result: pd.DataFrame, signal: pd.DataFrame, *, wait_days: int, first_buy_waits: bool = False
) -> dict:
    """Section 9: the stops and buy-backs of a brake run in one pass over its own ``ret`` (V by
    :func:`wallet_values`), the index and the rules of section 5, with the tool's wait read from the run's own tool
    orders. Returns ``stops``, ``unfilled``, ``buybacks``, ``buyback_due`` and ``buyback_held`` (lists)."""
    brake = parse_brake(**{k: result.attrs["brake"][k] for k in ("line", "level", "mode", "reading")})
    deposit = result.attrs["deposit"]
    wait_us = _count(wait_days, "wait_days") * DAY_US
    v = wallet_values(result["ret"].to_numpy(dtype=float), deposit).tolist()
    times = result.index.asi8.tolist()
    monday = (result.index.day_of_week.to_numpy() == MONDAY).tolist()
    i_close, _, avg = _signal_arrays(signal, result)
    n = len(v)
    starters = {"limit", "band", "reset", *(("first",) if first_buy_waits else ())}
    tool_starts = sorted(
        int(t) for t, r in zip(result.attrs["orders"], result.attrs["reasons"], strict=True) if r in starters
    )
    out: dict[str, list[int]] = {
        "stops": [],
        "unfilled": [],
        "buybacks": [],
        "buyback_due": [],
        "buyback_held": [],
    }
    armed, start, high = True, 1, -math.inf
    sale, dipped, due = -1, False, None
    for t in range(1, n):
        if armed:
            high = v[t] if t == start else max(high, v[t])
            if line_fires(brake, v[t], high, deposit):
                if t == n - 1:
                    out["unfilled"].append(t)
                    break
                out["stops"].append(t)
                armed, sale, dipped, due = False, t, False, None
            continue
        if due is None:
            if _buyback_signal(brake, t, sale, times, i_close, avg, monday, dipped):
                due = t
            elif brake.kind == "trend" and _is_dip(t, i_close, avg):
                dipped = True
        if due is None or t == n - 1:
            continue
        if brake.reading == "counts":
            starts = [times[u] for u in tool_starts if u < t] + [times[c] for c in out["buybacks"]]
            if starts and times[t] - max(starts) < wait_us:
                out["buyback_held"].append(t)
                continue
        out["buybacks"].append(t)
        out["buyback_due"].append(due)
        armed, start, due = True, t + 1, None
    return out


def check_events(result: pd.DataFrame, signal: pd.DataFrame) -> None:
    """:class:`ConsistencyError` unless the re-running's events equal :func:`recompute_events`'s (section 9)."""
    again = recompute_events(result, signal, wait_days=result.attrs["wait_days"])
    for key, value in again.items():
        if np.asarray(result.attrs[key], dtype=np.int64).tolist() != value:
            raise ConsistencyError(
                f"the re-running's {key} {np.asarray(result.attrs[key]).tolist()} differ from the one-pass "
                f"recompute's {value}"
            )


def check_orders(
    result: pd.DataFrame, *, wait_days: int, reading: str | None, first_buy_waits: bool = False
) -> None:
    """:class:`ConsistencyError` unless the orders of a run follow section 5 (stop rule 5):

    - ``reasons``, ``in_wait`` and ``order_targets`` align with ``orders``; the one ``first`` order is at close 0;
      orders are increasing closes 0 .. n-2; the stops and buy-backs listed are the stop and buyback orders;
    - stops and buy-backs alternate, starting with a stop; no tool order falls while the wallet is stopped; a stop
      orders all USDC and the wallet is all USDC at the close of its fill row;
    - the tool's wait: no band, reset or ('counts') buy-back order comes less than W days after the previous order
      that starts the wait (limit, band, reset, buyback; the first buy too with ``first_buy_waits``); ``in_wait``
      is True exactly for a limit fix or a ('separate') buy-back sent inside the wait. (So counted orders are at
      least W days apart, and no 30-day stretch holds more than ceil(30 / W) of them: hold_mix's cap.)
    - ``held`` and ``buyback_held`` lie in 1 .. n-2, increasing, on no order close; ``held`` never while stopped and
      ``buyback_held`` only while stopped."""
    wait_us = _count(wait_days, "wait_days") * DAY_US
    attrs = result.attrs
    orders = np.asarray(attrs["orders"], dtype=np.int64).tolist()
    reasons = [str(r) for r in attrs["reasons"]]
    in_wait = [bool(x) for x in attrs["in_wait"]]
    targets = np.asarray(attrs["order_targets"], dtype=float)
    n = len(result)
    if not len(orders) == len(reasons) == len(in_wait) == len(targets):
        raise ConsistencyError("reasons, in_wait and order_targets are not aligned with the engine's orders")
    if not orders or orders[0] != 0 or reasons[0] != "first" or "first" in reasons[1:]:
        raise ConsistencyError("the first buy must be the one order at close 0, with reason 'first'")
    if (
        not set(reasons) <= {*TOOL_REASONS, *BRAKE_REASONS}
        or (np.diff(orders) <= 0).any()
        or orders[-1] > n - 2
    ):
        raise ConsistencyError("orders must be increasing closes 0 .. n-2 with known reasons")
    stops = [t for t, r in zip(orders, reasons, strict=True) if r == "stop"]
    buybacks = [t for t, r in zip(orders, reasons, strict=True) if r == "buyback"]
    if (
        stops != np.asarray(attrs.get("stops", []), dtype=np.int64).tolist()
        or buybacks != np.asarray(attrs.get("buybacks", []), dtype=np.int64).tolist()
    ):
        raise ConsistencyError("the stops and buy-backs listed are not the run's stop and buyback orders")
    brake_seq = [r for r in reasons if r in BRAKE_REASONS]
    if brake_seq != ["stop", "buyback"] * (len(brake_seq) // 2) + ["stop"] * (len(brake_seq) % 2):
        raise ConsistencyError("stops and buy-backs must alternate, starting with a stop")
    position = result["position"].to_numpy(dtype=float)
    stopped = np.zeros(n, dtype=bool)
    ends = [*buybacks, n]
    for s, c in zip(stops, ends, strict=False):
        stopped[s + 1 : c + 1] = True
        if position[s + 1] != 0.0:
            raise ConsistencyError(f"the stop at close {s} did not leave the wallet all USDC")
    for t, r, w in zip(orders, reasons, targets.tolist(), strict=True):
        if r == "stop" and tuple(w) != CASH:
            raise ConsistencyError(f"the stop at close {t} does not order all USDC")
        if r in TOOL_REASONS and stopped[t]:
            raise ConsistencyError(f"a tool order ({r}) at close {t} while the wallet is stopped")
    times = result.index.asi8.tolist()
    counted_bb = reading == "counts"
    clock = times[0] if first_buy_waits else None
    for t, r, flag in zip(orders[1:], reasons[1:], in_wait[1:], strict=True):
        now = times[t]
        waiting = clock is not None and now - clock < wait_us
        held_back = r in ("band", "reset") or (r == "buyback" and counted_bb)
        if waiting and held_back:
            raise ConsistencyError(
                f"a {r} order at close {t} comes less than {wait_days} days after the wait started"
            )
        exempt = r == "limit" or (r == "buyback" and not counted_bb)
        if flag != (exempt and waiting):
            raise ConsistencyError(f"the in-wait flag of the {r} order at close {t} is wrong")
        if r in WAIT_STARTS:
            clock = now
    for key, inside in (("held", False), ("buyback_held", True)):
        rows = np.asarray(attrs.get(key, []), dtype=np.int64)
        if len(rows) and (
            rows[0] < 1
            or rows[-1] > n - 2
            or (np.diff(rows) <= 0).any()
            or np.isin(rows, orders).any()
            or (stopped[rows] != inside).any()
        ):
            raise ConsistencyError(
                f"{key} closes must be increasing closes 1 .. n-2 with no order, as stopped as rules say"
            )


def check_book(result: pd.DataFrame, bars: pd.DataFrame, costs: Costs, tol: float = 1e-12) -> None:
    """Section 9: replay the run in coin units and USDC cash (each fill re-cuts what is left after its legs' costs to
    the order's target vector; a leg costs ``usd * rate(usd) + gas``; the legs that trade are the fill log's) and
    require every return, weight and V to agree with the engine to ``tol`` (absolute; V relative), every fill row to
    follow an order, and every leg's USD size and cost to agree to ``tol`` of its V_open."""
    if not isinstance(costs, Costs):
        raise ValueError(f"check_book: costs must be a Costs instance, got {costs!r}")
    n = len(bars)
    o = [bars[(a, "open")].to_numpy(dtype=float).tolist() for a in ASSETS]
    c = [bars[(a, "close")].to_numpy(dtype=float).tolist() for a in ASSETS]
    fills = result.attrs["fills"]
    legs = {
        (int(b), ASSETS.index(str(a))): (float(u), float(k))
        for b, a, u, k in zip(fills["bar"], fills["asset"], fills["usd"], fills["cost"], strict=True)
    }
    orders = np.asarray(result.attrs["orders"], dtype=np.int64).tolist()
    target_at = {
        t + 1: tuple(w)
        for t, w in zip(orders, np.asarray(result.attrs["order_targets"]).tolist(), strict=True)
    }
    turnover = result["turnover"].to_numpy(dtype=float)
    ret = result["ret"].to_numpy(dtype=float)
    weights = result[list(WEIGHT_COLUMNS)].to_numpy(dtype=float)
    engine_v = wallet_values(ret, costs.capital_usd)
    fill_rows = np.flatnonzero(turnover > 0.0).tolist()
    if not set(fill_rows) <= set(target_at) or {b for b, _ in legs} != set(fill_rows):
        raise ConsistencyError("a fill row follows no order, or the fill log and the turnover disagree")
    units, cash, before = [0.0, 0.0], costs.capital_usd, costs.capital_usd
    for t in range(1, n):
        if turnover[t] > 0.0:
            target = target_at[t]
            vo = cash + sum(units[a] * o[a][t] for a in range(2))
            paid = 0.0
            for a in range(2):
                if (t, a) in legs:
                    usd = abs(target[a] * vo - units[a] * o[a][t])
                    cost = usd * costs.rate(usd) + costs.gas_usd_per_trade
                    if abs(usd - legs[(t, a)][0]) > tol * vo or abs(cost - legs[(t, a)][1]) > tol * vo:
                        raise ConsistencyError(f"the leg of {ASSETS[a]} on row {t} differs from the book's")
                    paid += cost
            after = vo - paid
            units = [target[a] * after / o[a][t] for a in range(2)]
            cash = (1.0 - (target[0] + target[1])) * after
        value = cash + sum(units[a] * c[a][t] for a in range(2))
        if abs(value / before - 1.0 - ret[t]) > tol or abs(value / engine_v[t] - 1.0) > tol:
            raise ConsistencyError(
                f"the return or value on row {t} differs from the book of coin units and cash"
            )
        if any(abs(units[a] * c[a][t] / value - weights[t, a]) > tol for a in range(2)):
            raise ConsistencyError(f"the weights on row {t} differ from the book of coin units and cash")
        before = value


# ------------------------------------------------------------------------------------------------ measures


STOP_COLUMNS = (
    "stop",
    "stop_ts",
    "high",
    "line_value",
    "v_stop",
    "v_open",
    "v_sale",
    "overshoot",
    "overshoot_type",
    "overshoot_before",
    "b_active",
    "below_d",
    "sale_vs_d",
    "kept_share",
    "buyback",
    "buyback_ts",
    "due_ts",
    "held_days",
    "not_bought_back",
    "usdc_days",
    "missed_rebound",
    "restop",
    "days_from_start",
)


def stop_rows(result: pd.DataFrame, bars: pd.DataFrame, signal: pd.DataFrame) -> list[dict]:
    """One row per filled stop (section 7; :data:`STOP_COLUMNS`), from the result and the window's index rows."""
    brake = parse_brake(**{k: result.attrs["brake"][k] for k in ("line", "level", "mode", "reading")})
    deposit = result.attrs["deposit"]
    v = wallet_values(result["ret"].to_numpy(dtype=float), deposit)
    times = result.index.asi8
    index = result.index
    i_close, i_open, _ = _signal_arrays(signal, bars)
    w = result[list(WEIGHT_COLUMNS)].to_numpy(dtype=float)
    o = [bars[(a, "open")].to_numpy(dtype=float) for a in ASSETS]
    c = [bars[(a, "close")].to_numpy(dtype=float) for a in ASSETS]
    stops = np.asarray(result.attrs["stops"], dtype=np.int64).tolist()
    buybacks = np.asarray(result.attrs["buybacks"], dtype=np.int64).tolist()
    dues = np.asarray(result.attrs["buyback_due"], dtype=np.int64).tolist()
    restarts = _armed_restarts(buybacks)
    n = len(result)
    rows = []
    for j, t in enumerate(stops):
        high = float(v[restarts[j] : t + 1].max())
        line = line_value(brake, high, deposit)
        wg = 0.0
        for a in range(2):
            wg += w[t, a] * (o[a][t + 1] / c[a][t] - 1.0)
        v_open = float(v[t] * (1.0 + wg))
        v_sale = float(v[t + 1])
        scale = high if brake.line == "A" else high - deposit
        bought = j < len(buybacks)
        cb = buybacks[j] if bought else -1
        later = stops[j + 1] if j + 1 < len(stops) else None
        b = brake.line == "B"
        rows.append(
            {
                "stop": t,
                "stop_ts": index[t],
                "high": high,
                "line_value": line,
                "v_stop": float(v[t]),
                "v_open": v_open,
                "v_sale": v_sale,
                "overshoot": (line - v_sale) / line,
                "overshoot_type": (line - v_sale) / scale,
                "overshoot_before": (line - v_open) / line,
                "b_active": b,
                "below_d": b and v_sale < deposit,
                "sale_vs_d": v_sale / deposit - 1.0 if b else math.nan,
                "kept_share": (v_sale - deposit) / (high - deposit) if b else math.nan,
                "buyback": cb,
                "buyback_ts": index[cb] if bought else pd.NaT,
                "due_ts": index[dues[j]] if bought else pd.NaT,
                "held_days": _days(times[cb] - times[dues[j]]) if bought else math.nan,
                "not_bought_back": not bought,
                "usdc_days": _days((times[cb] if bought else times[n - 1]) - times[t]),
                "missed_rebound": (i_open[cb + 1] if bought else i_close[n - 1]) / i_open[t + 1] - 1.0,
                "restop": bool(later is not None and times[later] - times[cb] <= RESTOP_DAYS * DAY_US)
                if bought
                else math.nan,
                "days_from_start": _days(times[t] - times[0]),
            }
        )
    return rows


RUN_MEASURES = (
    "F",
    "v_end",
    "total_return",
    "stops",
    "fired",
    "first_stop_days",
    "unfilled",
    "not_bought_back",
    "buybacks",
    "restops",
    "buyback_held",
    "usdc_days",
    "usdc_share",
    "b_active",
    "b_below_d",
    "b_worst_below_d",
    "b_kept_end",
    "overshoot_max",
    "tool_orders",
    "passes",
    "fees_pct_per_year",
    "fees_pct_per_year_tool",
    "fees_pct_per_year_brake",
    "gas_pct_per_year",
    "gas_pct_per_year_tool",
    "gas_pct_per_year_brake",
    "fees_usd_per_year_tool",
    "fees_usd_per_year_brake",
    "first_cost_pct",
)


def run_measures(
    result: pd.DataFrame, bars: pd.DataFrame, costs: Costs, signal: pd.DataFrame | None
) -> tuple[dict, list[dict]]:
    """Section 7's per-run measures (:data:`RUN_MEASURES`) and the run's :func:`stop_rows` (empty for R). F comes
    from ``holdmix.money_metrics`` (its fee check included); the fees are split by order reason, and the split must
    add up to money_metrics' totals (else :class:`ConsistencyError`)."""
    money = holdmix.money_metrics(result, costs)
    times = result.index.asi8
    span = _days(int(times[-1] - times[0]))
    year = YEAR_DAYS / span
    ret = result["ret"].to_numpy(dtype=float)
    deposit = costs.capital_usd
    v = wallet_values(ret, deposit)
    orders = np.asarray(result.attrs["orders"], dtype=np.int64)
    reasons = [str(r) for r in result.attrs["reasons"]]
    brake_rows = {int(t) + 1 for t, r in zip(orders.tolist(), reasons, strict=True) if r in BRAKE_REASONS}
    fills = result.attrs["fills"]
    bar = fills["bar"].to_numpy()
    usd = fills["usd"].to_numpy(dtype=float)
    leg_cost = fills["cost"].to_numpy(dtype=float)
    v_open = usd / np.abs(
        fills["weight_after"].to_numpy(dtype=float) - fills["weight_before"].to_numpy(dtype=float)
    )
    gas = costs.gas_usd_per_trade
    later = bar >= 2
    is_brake = np.isin(bar, sorted(brake_rows)) & later
    is_tool = later & ~is_brake
    split = {}
    for name, mask in (("tool", is_tool), ("brake", is_brake)):
        split[f"fees_pct_per_year_{name}"] = (
            100.0 * year * math.fsum(((leg_cost[mask] - gas) / v_open[mask]).tolist())
        )
        split[f"gas_pct_per_year_{name}"] = 100.0 * year * math.fsum((gas / v_open[mask]).tolist())
        split[f"fees_usd_per_year_{name}"] = year * math.fsum((leg_cost[mask] - gas).tolist())
    for key in ("fees_pct_per_year", "gas_pct_per_year"):
        total = split[f"{key}_tool"] + split[f"{key}_brake"]
        if abs(total - money[key]) > 1e-12 * max(abs(money[key]), 1e-300):
            raise ConsistencyError(
                f"the tool's and the brake's {key} ({total!r}) do not add up to {money[key]!r}"
            )
    out = {
        "F": -money["max_drawdown"],
        "v_end": float(v[-1]),
        "total_return": money["total_return"],
        "fees_pct_per_year": money["fees_pct_per_year"],
        "gas_pct_per_year": money["gas_pct_per_year"],
        "first_cost_pct": money["first_cost_pct"],
        "tool_orders": sum(r in ("limit", "band", "reset") for r in reasons),
        **split,
    }
    if result.attrs.get("brake") is None:
        out.update(
            stops=0,
            fired=False,
            first_stop_days=math.nan,
            unfilled=False,
            not_bought_back=False,
            buybacks=0,
            restops=0,
            buyback_held=0,
            usdc_days=0.0,
            usdc_share=0.0,
            b_active=False,
            b_below_d=0,
            b_worst_below_d=math.nan,
            b_kept_end=math.nan,
            overshoot_max=math.nan,
            passes=1,
        )
        return out, []
    rows = stop_rows(result, bars, signal)
    brake = parse_brake(**{k: result.attrs["brake"][k] for k in ("line", "level", "mode", "reading")})
    stops = [r["stop"] for r in rows]
    buybacks = np.asarray(result.attrs["buybacks"], dtype=np.int64).tolist()
    active = False
    if brake.line == "B":
        restarts = _armed_restarts(buybacks)
        stretches = list(zip(restarts, stops, strict=False))
        if len(buybacks) == len(stops):
            stretches.append((restarts[-1], len(v) - 1))
        active = any(float(v[lo : hi + 1].max()) >= (1.0 + brake.gain) * deposit for lo, hi in stretches)
    peak = float(v[1:].max())
    below = [r["sale_vs_d"] for r in rows if r["below_d"]]
    out.update(
        stops=len(rows),
        fired=bool(rows),
        first_stop_days=rows[0]["days_from_start"] if rows else math.nan,
        unfilled=bool(len(result.attrs["unfilled"])),
        not_bought_back=bool(result.attrs["not_bought_back"]),
        buybacks=len(buybacks),
        restops=sum(1 for r in rows if r["restop"] is True),
        buyback_held=len(result.attrs["buyback_held"]),
        usdc_days=math.fsum(r["usdc_days"] for r in rows),
        usdc_share=math.fsum(r["usdc_days"] for r in rows) / span,
        b_active=active,
        b_below_d=len(below),
        b_worst_below_d=min(below) if below else math.nan,
        b_kept_end=(float(v[-1]) - deposit) / (peak - deposit) if active else math.nan,
        overshoot_max=max(r["overshoot"] for r in rows) if rows else math.nan,
        passes=int(result.attrs["passes"]),
    )
    return out, rows


def cost_vs_reference(v_end: float, v_end_ref: float) -> float:
    """C = 1 - V_end / V_end(R) (section 7): negative when the brake helped."""
    return 1.0 - v_end / v_end_ref


# ------------------------------------------------------------------------------------------------ windows


def rolling_windows(source: str) -> list[tuple[int, pd.Timestamp, pd.Timestamp]]:
    """Section 6's 24-month windows from the calendar only: window k holds the bars of M_k .. M_(k+23) (M_k = January
    2017 + k months), closes from the 2nd of M_k to the 1st of M_(k+24) at 00:00 UTC, both included. Kraken k = 0..48;
    Binance the k whose first close is on or after 2017-08-18 (k = 8..48). ``(k, first close, last close)``."""
    if source not in holdmix.SOURCES:
        raise ValueError(f"source must be one of {holdmix.SOURCES}, got {source!r}")
    first_close = holdmix.FIRST_CLOSE[source]
    month0 = pd.Timestamp("2017-01-01", tz="UTC")
    out = []
    for k in range(N_WINDOWS):
        first = month0 + pd.DateOffset(months=k) + pd.Timedelta(days=1)
        if first >= first_close:
            out.append((k, first, month0 + pd.DateOffset(months=k + WINDOW_MONTHS)))
    return out


def overlaps(k: int, year: int) -> bool:
    """Window k (months M_k .. M_(k+23)) overlaps calendar year Y: 12 (Y - 2017) - 23 <= k <= 12 (Y - 2017) + 11
    (D4)."""
    first = 12 * (year - 2017)
    return first - (WINDOW_MONTHS - 1) <= k <= first + 11


def windows_without(windows: Iterable[int], years: Iterable[int]) -> list[int]:
    """The windows of ``windows`` overlapping none of ``years``, sorted."""
    years = tuple(years)
    return sorted(int(k) for k in windows if not any(overlaps(int(k), y) for y in years))


def boom_removals(returns: Mapping[int, float]) -> list[dict]:
    """D4's boom-year checks: without BTC's best calendar year, then without its two best (``returns``: Kraken's
    ``holdmix.year_returns``; ties to the earlier year). Each ``{"name", "years"}``."""
    missing = [y for y in TRAIN_YEARS if y not in returns]
    if missing:
        raise ValueError(f"boom_removals: no yearly return for {missing}")
    ranked = {y: returns[y] for y in TRAIN_YEARS}
    return [{"name": f"boom: without the best {n}", "years": holdmix.best_years(ranked, n)} for n in (1, 2)]


# ------------------------------------------------------------------------------------------------ the rules


RUN_KEYS = ("source", "cost", "reading", "line", "level", "mode", "s", "f", "window")
REF_LINE = "R"  # the reference runs (the tool alone): reading and mode "none", level NaN


def _failed(frame: pd.DataFrame) -> bool:
    return bool((frame["status"].to_numpy() != OK).any())


def _pct(values, q: float = PERCENTILE) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def _mixes(frame: pd.DataFrame) -> list[tuple[float, float]]:
    return sorted(set(zip(frame["s"].tolist(), frame["f"].tolist(), strict=True)))


def _of_mix(frame: pd.DataFrame, mix: tuple[float, float]) -> pd.DataFrame:
    return frame[(frame["s"].to_numpy() == mix[0]) & (frame["f"].to_numpy() == mix[1])]


def _pairs(frame: pd.DataFrame) -> list[tuple]:
    return sorted(zip(frame["s"].tolist(), frame["f"].tolist(), frame["window"].tolist(), strict=True))


def _looser_key(line: str, level: float) -> float:
    return -level if line == "A" else level


def _no_larger(a: Mapping, b: Mapping) -> bool:
    """(C~, C-) of ``a`` no larger than ``b``'s: C~ within TIE_TOL is a tie, then C- exactly."""
    if abs(a["C_med"] - b["C_med"]) <= TIE_TOL:
        return a["C_mean"] <= b["C_mean"]
    return a["C_med"] < b["C_med"]


def _smaller(a: Mapping, b: Mapping) -> bool:
    """(C~, C-) of ``a`` strictly smaller than ``b``'s (C~ within TIE_TOL is a tie, then C- exactly)."""
    if abs(a["C_med"] - b["C_med"]) <= TIE_TOL:
        return a["C_mean"] < b["C_mean"]
    return a["C_med"] < b["C_med"]


def _within_tie(entries: Sequence[Mapping]) -> list[Mapping]:
    best = min(e["C_med"] for e in entries)
    return [e for e in entries if abs(e["C_med"] - best) <= TIE_TOL]


def d1(pool: pd.DataFrame, line: str, mode: str, reading: str) -> dict:
    """D1, the default level for one line type, buy-back mode and reading, on one pool (one source and cost level,
    holding the reference runs, ``line == "R"``). ``default`` is the level, :data:`NO_DEFAULT` or :data:`MISSING`;
    ``table`` holds each level's numbers (Q, the per-mix Q, the worst F, C~, C-, the buy-backs and re-stops)."""
    if line not in LINES or mode not in MODES or reading not in READINGS:
        raise ValueError(f"d1: unknown line, mode or reading {(line, mode, reading)!r}")
    ref = pool[pool["line"].to_numpy() == REF_LINE]
    rows = pool[
        (pool["line"].to_numpy() == line)
        & (pool["mode"].to_numpy() == mode)
        & (pool["reading"].to_numpy() == reading)
    ]
    out = {
        "line": line,
        "mode": mode,
        "reading": reading,
        "default": MISSING,
        "Q0": None,
        "table": [],
        "reason": None,
    }
    if ref.empty or rows.empty:
        out["reason"] = "no runs in the pool"
        return out
    if _failed(ref) or _failed(rows):
        out["reason"] = "a run in the pool failed (stop rule 4)"
        return out
    pairs = _pairs(ref)
    if len(set(pairs)) != len(pairs):
        raise ValueError("d1: the reference runs repeat a (mix, window) pair")
    q0 = _pct(ref["F"])
    worst0 = float(ref["F"].max())
    mixes = _mixes(ref)
    q0_mix = {m: _pct(_of_mix(ref, m)["F"]) for m in mixes}
    table = []
    for level in sorted(set(rows["level"].tolist())):
        at = rows[rows["level"].to_numpy() == level]
        if _pairs(at) != pairs:
            raise ValueError(
                f"d1: level {level} does not hold exactly the reference runs' (mix, window) pairs"
            )
        q = _pct(at["F"])
        q_mix = {m: _pct(_of_mix(at, m)["F"]) for m in mixes}
        pooled = PROTECT_LEFT * q <= PROTECT_RIGHT * q0
        per_mix = all(PROTECT_LEFT * q_mix[m] <= PROTECT_RIGHT * q0_mix[m] for m in mixes)
        worst = float(at["F"].max())
        buybacks = int(at["buybacks"].sum())
        restops = int(at["restops"].sum())
        table.append(
            {
                "level": float(level),
                "runs": len(at),
                "Q": q,
                "Q_mix": {f"{s:g}/{f:g}": q_mix[(s, f)] for s, f in mixes},
                "Q0_mix": {f"{s:g}/{f:g}": q0_mix[(s, f)] for s, f in mixes},
                "pooled": bool(pooled),
                "per_mix": bool(per_mix),
                "worst_F": worst,
                "worst_F0": worst0,
                "worst_guard": bool(worst <= worst0),
                "meaningful": bool(pooled and per_mix and worst <= worst0),
                "C_med": float(np.median(at["C"].to_numpy(dtype=float))),
                "C_mean": float(np.mean(at["C"].to_numpy(dtype=float))),
                "buybacks": buybacks,
                "restops": restops,
                "restop_share": restops / buybacks if buybacks else MISSING,
            }
        )
    out.update(Q0=q0, table=table)
    if q0 == 0.0:
        out.update(default=NO_DEFAULT, reason="Q0 = 0: the reference never falls")
        return out
    meaningful = [e for e in table if e["meaningful"]]
    if not meaningful:
        out.update(default=NO_DEFAULT, reason="no level gives meaningful protection")
        return out
    candidates = _within_tie(meaningful)
    pick = min(candidates, key=lambda e: (e["C_mean"], _looser_key(line, e["level"])))
    out.update(default=pick["level"], reason=None, candidates=[e["level"] for e in candidates])
    return out


def _at_default(d: Mapping) -> dict | None:
    level = d["default"]
    if isinstance(level, str):
        return None
    return next(e for e in d["table"] if e["level"] == level)


def _entry(d: Mapping, mode: str) -> dict:
    e = _at_default(d)
    return {
        "mode": mode,
        "level": d["default"],
        "C_med": e["C_med"],
        "C_mean": e["C_mean"],
        "buybacks": e["buybacks"],
        "restop_share": e["restop_share"],
    }


def d2(d1s: Mapping[str, Mapping], line: str) -> dict:
    """D2, the default buy-back for one line type and reading, from that reading's D1 results by mode (``d1s``).
    ``mode`` is an automatic mode, :data:`WAIT` (the customer's own, at wait-30's D1 level and numbers),
    :data:`NO_DEFAULT` (the owner decides) or :data:`MISSING`."""
    out = {"line": line, "mode": MISSING, "level": MISSING, "basis": None, "C_med": None, "C_mean": None}
    out.update(automatic=[], wait30=None, case=None)
    needed = (*AUTO_MODES, WAIT_MODE)
    missing = [m for m in needed if _is_word(d1s[m]["default"], MISSING)]
    if missing:
        out["case"] = f"MISSING: D1 is MISSING for {missing}"
        return out
    automatic = []
    for m in AUTO_MODES:
        if _at_default(d1s[m]) is None:
            continue
        e = _entry(d1s[m], m)
        share = e["restop_share"]
        e["eligible"] = not isinstance(share, str) and share <= RESTOP_MAX
        automatic.append(e)
    eligible = [e for e in automatic if e["eligible"]]
    best = None
    if eligible:
        best = min(
            _within_tie(eligible), key=lambda e: (e["C_mean"], e["buybacks"], D2_TIE_ORDER.index(e["mode"]))
        )
    wait = _entry(d1s[WAIT_MODE], WAIT_MODE) if _at_default(d1s[WAIT_MODE]) is not None else None
    out.update(automatic=automatic, wait30=wait)
    if best is not None and wait is not None:
        pick, case = (
            (best, "automatic no larger than wait-30")
            if _no_larger(best, wait)
            else (wait, "wait-30 smaller")
        )
    elif best is not None:
        pick, case = best, "wait-30 has NO DEFAULT"
    elif wait is not None:
        pick, case = wait, "no automatic mode is eligible or has a default"
    else:
        out.update(mode=NO_DEFAULT, level=NO_DEFAULT, case="neither: the owner decides")
        return out
    out.update(
        mode=WAIT if pick["mode"] == WAIT_MODE else pick["mode"],
        level=pick["level"],
        basis=pick["mode"],
        C_med=pick["C_med"],
        C_mean=pick["C_mean"],
        case=case,
    )
    return out


def _has_default(d: Mapping) -> bool:
    return not isinstance(d["level"], str)


def d3(d2a: Mapping, d2b: Mapping) -> dict:
    """D3, which line the app shows first: the type with the smaller (C~, C-) at its default (ties to A); the other
    when one has NO DEFAULT; :data:`NONE` when both; :data:`MISSING` when either D2 is MISSING."""
    if _is_word(d2a["mode"], MISSING) or _is_word(d2b["mode"], MISSING):
        return {"line": MISSING, "mode": MISSING, "level": MISSING}
    has = {line: d for line, d in (("A", d2a), ("B", d2b)) if _has_default(d)}
    if not has:
        return {"line": NONE, "mode": NONE, "level": NONE}
    if len(has) == 1:
        line = next(iter(has))
    else:
        line = "A" if _no_larger(d2a, d2b) else "B"
    return {"line": line, "mode": has[line]["mode"], "level": has[line]["level"]}


def d6(d2s: Mapping[str, Mapping[str, Mapping]]) -> dict:
    """D6 (R4), the tool's limit reading, from each reading's D2 by line type (``d2s[reading][line]``)."""
    out = {"in_force": IN_FORCE, "recommended": MISSING, "compared": {}, "needs_owner_approval": False}
    if any(_is_word(d2s[r][line]["mode"], MISSING) for r in READINGS for line in LINES):
        out["reason"] = "a D2 is MISSING"
        return out
    types = [line for line in LINES if all(_has_default(d2s[r][line]) for r in READINGS)]
    compared = {line: _smaller(d2s["separate"][line], d2s["counts"][line]) for line in types}
    out["compared"] = compared
    if not types:
        out.update(recommended="counts", reason="no line type has a default under both readings")
    elif all(compared.values()):
        out.update(recommended="separate", reason="'separate' is strictly cheaper for every line type")
    else:
        out.update(recommended="counts", reason="'separate' is not strictly cheaper for every line type")
    out["needs_owner_approval"] = out["recommended"] == "separate"
    return out


def defaults(pool: pd.DataFrame, reading: str) -> dict:
    """D1 for every line type and mode, D2 for each line type, and D3, on one pool and reading."""
    d1s = {line: {mode: d1(pool, line, mode, reading) for mode in MODES} for line in LINES}
    d2s = {line: d2(d1s[line], line) for line in LINES}
    return {"reading": reading, "D1": d1s, "D2": d2s, "D3": d3(d2s["A"], d2s["B"])}


def _key(d: Mapping, line: str | None = None):
    """A default as compared by D4: (type, mode, level), or the outcome word (NO DEFAULT, none or MISSING)."""
    if isinstance(d["level"], str):
        return d["level"]
    return (line or d["line"], d["mode"], d["level"])


def d4(headline: Mapping, checks: Mapping[str, Mapping | None]) -> dict:
    """D4's labels for each line type's default and D3's choice: ``headline`` and each check are :func:`defaults`
    outputs (a check of None is MISSING, e.g. a boom removal leaving fewer than 12 windows)."""
    labels = {}
    for what in (*LINES, "first"):

        def key(d, what=what):
            return _key(d["D3"]) if what == "first" else _key(d["D2"][what], what)

        mine = key(headline)
        per, moved, missing = {}, [], []
        for name, check in checks.items():
            if check is None:
                per[name] = MISSING
                missing.append(name)
                continue
            theirs = per[name] = key(check)
            if _is_word(theirs, MISSING):
                missing.append(name)
            elif theirs != mine:
                moved.append(name)
        if _is_word(mine, MISSING):
            label = f"{MISSING} (headline)"
        elif moved:
            label = f"{NOT_ROBUST} ({', '.join(moved + [f'{m}: MISSING' for m in missing])})"
        elif missing:
            label = f"{MISSING} ({', '.join(missing)})"
        else:
            label = ROBUST
        labels[what] = {"default": mine, "label": label, "checks": per, "moved": moved, "missing": missing}
    return labels


def d5(pool: pd.DataFrame, stops: pd.DataFrame, d2_line: Mapping, reading: str) -> dict:
    """D5, the promise number for one line type at its D1-D2 default: the largest overshoot (app unit) and its 95th
    percentile over every stop of the pool's runs at the default, the worst F with the brake on and B's worst sale
    below D (:data:`NONE` when no B stop sold below D). No stops, or a default that is not a level, gives MISSING."""
    line = d2_line["line"]
    out = {
        "line": line,
        "status": MISSING,
        "Z": None,
        "Z_p95": None,
        "worst_F": None,
        "b_worst_below_d": None,
    }
    if not _has_default(d2_line):
        out["reason"] = f"no default ({d2_line['level']})"
        return out
    keys = {"line": line, "mode": d2_line["basis"], "level": d2_line["level"], "reading": reading}
    runs = pool
    for col, value in keys.items():
        runs = runs[runs[col].to_numpy() == value]
    if runs.empty or _failed(runs):
        out["reason"] = "no runs, or a failed run, at the default"
        return out
    mine = stops[stops["run_id"].isin(runs["run_id"]).to_numpy()]
    if mine.empty:
        out["reason"] = "no stops at the default"
        return out
    over = mine["overshoot"].to_numpy(dtype=float)
    below = mine.loc[mine["below_d"].to_numpy(dtype=bool), "sale_vs_d"].to_numpy(dtype=float)
    out.update(
        status=OK,
        stops=len(mine),
        Z=float(over.max()),
        Z_p95=_pct(over, PROMISE_PERCENTILE),
        worst_F=float(runs["F"].max()),
        b_worst_below_d=(float(below.min()) if len(below) else NONE) if line == "B" else None,
    )
    return out


def level_table(pool: pd.DataFrame, stops: pd.DataFrame) -> list[dict]:
    """The description table of section 14: per (line, level, mode, reading), and R, on one pool: runs, failed, fire
    rate, stops, the 90th percentile and worst of F (and per mix), C~ and C-, buy-backs, re-stops and their share,
    held buy-backs, the median share of time in USDC, last-close crossings, stops not bought back, the largest and
    95th-percentile overshoot (and before costs), the distinct sale dates, the median missed rebound, B's sales below
    D, the median fees a year (tool, brake), and for runs where B was active at some close their count and the median
    share of the peak profit kept at the end (section 7). Per mix: Q, the fire rate and C~."""
    out = []
    groups = pool.groupby(["line", "level", "mode", "reading"], sort=True, dropna=False)
    for (line, level, mode, reading), rows in groups:
        ok = rows[rows["status"].to_numpy() == OK]
        st = stops[stops["run_id"].isin(ok["run_id"]).to_numpy()]
        over = st["overshoot"].to_numpy(dtype=float)
        entry = {
            "line": line,
            "level": None if pd.isna(level) else float(level),
            "mode": mode,
            "reading": reading,
            "runs": len(rows),
            "failed": int(len(rows) - len(ok)),
        }
        if not ok.empty:
            entry.update(
                fire_rate=float(ok["fired"].astype(bool).mean()),
                stops=int(ok["stops"].sum()),
                Q=_pct(ok["F"]),
                worst_F=float(ok["F"].max()),
                Q_mix={f"{s:g}/{f:g}": _pct(_of_mix(ok, (s, f))["F"]) for s, f in _mixes(ok)},
                fire_rate_mix={
                    f"{s:g}/{f:g}": float(_of_mix(ok, (s, f))["fired"].astype(bool).mean())
                    for s, f in _mixes(ok)
                },
                C_med_mix={f"{s:g}/{f:g}": float(np.median(_of_mix(ok, (s, f))["C"])) for s, f in _mixes(ok)},
                C_med=float(np.median(ok["C"])),
                C_mean=float(np.mean(ok["C"])),
                buybacks=int(ok["buybacks"].sum()),
                restops=int(ok["restops"].sum()),
                restop_share=float(ok["restops"].sum() / ok["buybacks"].sum())
                if ok["buybacks"].sum()
                else None,
                buyback_held=int(ok["buyback_held"].sum()),
                usdc_share_median=float(np.median(ok["usdc_share"])),
                unfilled=int(ok["unfilled"].astype(bool).sum()),
                not_bought_back=int(ok["not_bought_back"].astype(bool).sum()),
                overshoot_max=float(over.max()) if len(over) else None,
                overshoot_p95=_pct(over, PROMISE_PERCENTILE) if len(over) else None,
                overshoot_before_max=float(st["overshoot_before"].max()) if len(over) else None,
                distinct_sale_dates=int(st["stop_ts"].nunique()),
                missed_rebound_median=float(np.median(st["missed_rebound"])) if len(over) else None,
                b_below_d=int(st["below_d"].astype(bool).sum()),
                fees_tool_median=float(np.median(ok["fees_pct_per_year_tool"])),
                fees_brake_median=float(np.median(ok["fees_pct_per_year_brake"])),
                b_active_runs=int(ok["b_active"].astype(bool).sum()),
                b_kept_end_median=float(np.median(kept))
                if len(kept := ok.loc[ok["b_active"].astype(bool), "b_kept_end"])
                else None,
            )
        out.append(entry)
    return out
