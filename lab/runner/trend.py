"""trend-steady: the weekly trend rule, its one executor, the stop-loss variant and the study's luck controls.

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the
reference rebalancer, not NautilusTrader (AGENTS.md hard rule 3). ``research/trend-steady/PLAN.md`` is the contract;
section numbers below are that file's. No existing file is changed: every run hands a ``decide`` callback to
``portfolio._simulate``, exactly as ``portfolio.rebalance`` and ``holdmix.hold_mix`` do, and ``lab/search`` and
``lab/validation`` are used as they are.

The rule (section 4)
--------------------
For coin a in (BTC, ETH), at close t: SMA_a(t; L) = the mean of the closes of rows t - L + 1 .. t, **close t
included** (:func:`sma`, computed per window as ``math.fsum(window) / L``, never as a running sum, so the batch and
the live :class:`TrendStream` agree bit for bit), and m_a(t) = close_a(t) / SMA_a(t; L) - 1 (:func:`sma_distance`).
Activation A = max(:data:`R0`, L - 1) rows (:func:`activation`; every run starts at its panel's row 0). Check closes
are the rows >= A whose close falls on ``weekday`` (``index.day_of_week``; 0 = Monday 00:00 UTC, the bar of Sunday;
:func:`check_closes`); a missing check close is skipped. The state z_a starts ``out``; at a check close out -> in if
m_a > +delta and in -> out if m_a < -delta (both strict), otherwise unchanged; it is held between check closes
(:func:`trend_states`). The trend target is w_a = s*f*[z_BTC = in] and s*(1 - f)*[z_ETH = in] (s the crypto share,
f = 0.50 the split, USDC the rest; :func:`in_force`).

The one executor (sections 4 and 9, amendment M11)
--------------------------------------------------
:func:`run_states` takes a per-row array of target vectors (the vector in force decided at each close, point in
time) and sends an order at close t when the vector differs from close t - 1's (exact float comparison; before row 0
the book is all USDC), or when the weights at close t breach a Steady limit (``portfolio._breach_test`` at the
limits themselves), in which case it orders the vector in force. One order per close, always the full vector, filled
at the next open; the decision at the last close is never sent. Every executor uses it: S, theta_final, the grid
steps, S(s_k), N0, X, R_0 and its shifts, the stop variant's runs, R_0^phi, its shifts and placebo stops. ``states``
and ``locks`` only label each order's reason; they never decide. Reasons (:data:`REASONS`): ``stop`` (a lock turned
on), else ``switch`` (a coin's trend state changed), else ``unlock`` (a lock turned off with no state change: only in
placebo series), else ``re-cut`` (the vector changed for another reason: a new s between source folds), and
``limit`` (the vector did not change; a breach).

Result: ``portfolio._simulate``'s DataFrame and attrs, plus ``targets`` (the per-row vectors), ``reasons`` (one per
entry of ``orders``), ``switches`` (per order: the coins whose in-force state, target > 0, changed at that close),
``order_targets`` and ``order_hash`` (:func:`order_hash`: what must not depend on costs or the wallet size, stop
rule 13). :func:`trend_backtest` (the ``BacktestFn``) adds ``z``, ``checks``, ``activation`` and ``state_hash``.

The stop-loss variant (section 11A)
-----------------------------------
V = ``np.cumprod(1 + ret)`` of the run's own result; H = the largest V from the reference close (row 0, or the
close right after the latest stop event) to t; f = V / H - 1. A stop event is the first close t >= the reference
close with f <= -phi (a fall of exactly phi counts). It locks both coins; coin a is unlocked at the first close
strictly after the event at which z_a turns from out to in (an up-turn on the event close itself does not count).
The in-force target is the trend target times [not locked] (:func:`in_force`). Events are found by re-running
(:func:`stop_events`): run with the events so far, find the next event on that run's V, add it, run again, until
there is none. :func:`recompute_stop_events` finds the same events in one pass over a run's own ``ret`` (stop rule
13's check).

The harness and the comparators (sections 7, 9 and 11A)
-------------------------------------------------------
H0: every run starts at its own panel's row 0 and ends at a close taken from the Kraken panel (:func:`h0_slice`;
:func:`fold_windows` gives the folds of ``walk_forward(2190, 365, 365, expanding=True)``). :func:`stitched_schedule`
builds R_0's :class:`Schedule` from S's fold runs (the state pair and s of the fold that holds each check close, and
fold 0's rows before c_0, common to every series); :func:`shifted` is B3's check-close shift, :func:`run_span` runs
R_0, its shifts, R_0^phi, its weekly-segment shifts (:func:`segment_shift`) and its placebo stops
(:func:`placebo_stops`) through the one executor from row 0. :func:`always_in_n0` and :func:`exposure_x` (also N0^phi
and X^phi) copy S's in-force targets up to close t0 - 1, so they hold S's book at t0 bit for bit
(:func:`same_book_at`, stop rule 14). :func:`fresh_customer` restarts the book, the high and the locks at t0.

Pinned readings where the plan is loosely worded (each fixed before any result)
------------------------------------------------------------------------------
- **First buys** (P, section 11): each coin's first trend-state change in a run (always out -> in, from the start
  state) is its first buy and is not counted.
- **Completed out-spells** (P's description, M20): a coin's counted out -> in changes (every out -> in after the
  first buy ends an out-spell).
- **R1's mean** (section 12): 30 x (orders filled in kept rows) / (calendar days the kept rows cover, the sum of each
  kept row's bar length, :func:`covered_days`); "30 consecutive days" are the windows (t - 30 days, t] ending at
  each kept close, as the trade-frequency table counts them (:func:`rolling_count`).
- **The weekly segments** (section 11A): segment k is the rows c_k .. c_(k+1) - 1, the last one c_(W-1) .. n - 2
  (the last close but one); rows before c_0 keep their own entries (common start). The last close, in no segment,
  takes the shifted entry of the close before it: its decision is never filled, so this changes no return, and a
  shifted plain-rule series equals B3's check-close shift on every row (:func:`segment_source_rows`).
- **The stop variant's overall order, for stop rule 18** (:func:`reported_verdict`): NOT TRIGGERED < NO EDGE <
  STOP DOES NOT HELP < INCONCLUSIVE < STOP HELPS (a run whose stop never touched the kept rows supports the stop
  least). Ties between two runs go to the amendment run's string.
- **Narrowing** (section 8): each allowed value carries the deepest of its grid step's and its S(s_k)'s G6 statistic.

pandas caveat (as in portfolio.py): ``attrs`` holds arrays and frames; drop them (``piece.attrs = {}``) before
``pd.concat`` or ``to_parquet``.
"""

from __future__ import annotations

import hashlib
import math
import numbers
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from lab.runner.portfolio import (
    ASSETS,
    WEIGHT_COLUMNS,
    _breach_test,
    _simulate,
    check_targets,
    make_panel,
    validate_panel,
)
from lab.runner.reference import Costs, _check_params, _param_float, _param_int, _real
from lab.runner.steady import (
    SliceMismatchError,
    Window,
    _limit_values,
    e1_rank,
    fold_window,
    paired_bootstrap,
)
from lab.search.space import Param
from lab.search.study import load_trial_returns
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward

__all__ = [
    "ALLOWED_S",
    "CONTROLS_BUDGET_MINUTES",
    "E5A_ITEMS",
    "E7_ITEMS",
    "FIRST_ACTIVE_ROW",
    "F_SPLIT",
    "HEADROOM",
    "LEAD_GUARD",
    "PARAM_NAMES",
    "R0",
    "REASONS",
    "RUN_BUDGET_MINUTES",
    "SL_E5_ITEMS",
    "SL_E7_ITEMS",
    "SL_ITEMS",
    "SPECS",
    "STOP_LEVELS",
    "S_SHARE",
    "TIMING_KEYS",
    "WARMUP",
    "WEEKDAY",
    "Schedule",
    "TrendStates",
    "TrendStream",
    "activation",
    "active_report",
    "active_stats",
    "always_in_n0",
    "bar_years",
    "boom_holds",
    "boom_years",
    "check_closes",
    "check_feasibility",
    "check_share",
    "covered_days",
    "default_share",
    "e1_test",
    "e2_holds",
    "e2_test",
    "e3_holds",
    "e5a_holds",
    "e9_holds",
    "exposure_target",
    "exposure_x",
    "fold_windows",
    "fresh_customer",
    "from_t0",
    "g3_g4",
    "g6_holds",
    "g6_statistic",
    "g8_excess_pass",
    "garch_panel",
    "guarded",
    "guarded_offsets",
    "h0_slice",
    "headline",
    "in_force",
    "keeps_share",
    "lag_offsets",
    "lead_offsets",
    "lock_series",
    "loyo",
    "measurement_points",
    "narrowing",
    "order_hash",
    "order_log",
    "overall_stop_outcome",
    "parse_params",
    "placebo_stops",
    "plateau_step",
    "plateau_steps",
    "power_count",
    "project_cpu_minutes",
    "projection_allows",
    "r1_check",
    "random_walk_panel",
    "rank_holds",
    "recompute_stop_events",
    "reported_verdict",
    "riskiest_step",
    "rolling_count",
    "rolling_order_count",
    "run_span",
    "run_states",
    "same_book_at",
    "segment_shift",
    "segment_source_rows",
    "share_targets",
    "shifted",
    "sl_b",
    "sl_e5_holds",
    "sl_power",
    "sma",
    "sma_distance",
    "span_targets",
    "state_hash",
    "stitched_locks",
    "stitched_schedule",
    "stop_events",
    "stop_level_line",
    "stop_verdict",
    "trade_frequency",
    "train_grid",
    "trend_backtest",
    "trend_states",
    "triggered",
    "verdict",
    "without_years",
    "year_returns",
]

# ------------------------------------------------------------------------------------------------ pinned values

HEADROOM = 0.02  # every target stays this far inside every Steady limit (section 4)
R0 = 199  # activation A = max(R0, L - 1): L_max - 1, so every L in the box starts on the same row
S_SHARE = 0.50  # the calibration test's crypto share (section 9)
F_SPLIT = 0.50  # the BTC/ETH split, fixed (section 5)
WEEKDAY = 0  # Monday 00:00 UTC (the bar of Sunday)
WARMUP = 2190  # harness H0: walk_forward_optimize(warmup=2190), every run from row 0 (section 7)
PARAM_NAMES = ("lookback", "buffer", "crypto_share")
SPECS = (
    Param("lookback", "int", 20, 200, log=True),
    Param("buffer", "float", 0.005, 0.10, log=True),
    Param("crypto_share", "float", 0.30, 0.60),
)
ALLOWED_S = (0.30, 0.40, 0.50, 0.60)  # the customer setting (Branch R, section 8)
PLATEAU_SHARE_EXTREMES = (0.24, 0.72)  # 0.30 x 0.8 and 0.60 x 1.2 (stop rule 12)
STOP_LEVELS = (0.20, 0.30, 0.40)  # the owner's levels (section 11A)
RUN_BUDGET_MINUTES = 60  # stop rule 17: run 0 and each amendment run
CONTROLS_BUDGET_MINUTES = 120  # stop rule 17: A0
TIMING_KEYS = ("study", "run", "stop_run", "bootstrap")  # what the projection guard re-times (section 7)
LEAD_GUARD = 52  # weeks: shifts u = 1..52 lead the schedule and are never in a null (section 9)
FIRST_ACTIVE_ROW = 204  # the first row on which any trial can hold a coin (sections 6, 14)
FOLD_ROWS = 365  # walk_forward(2190, 365, 365, expanding=True)
ALPHA = 0.05
PLATEAU_FACTORS = (0.8, 1.2)
PLATEAU_KEEP = 0.7
SEED_SHARPE_GAP = 0.25  # E5(a)
MIN_SWITCHES = 20  # P
MIN_SWITCH_FOLDS = 4
MIN_STOPS = 3  # SL-P
MIN_STOP_YEARS = 2
WINDOW_DAYS = 30
R1_MEAN = 2.0
R1_MOST = 5
MC_MEAN_BLOCK = 20  # G6's statistic: overfitting_report's bootstrap
MC_SIMS = 1000
E2_MEAN_BLOCK = 60
E2_RESAMPLES = 10_000
TIE_TOL = 1e-12  # the default's tie (M19)
LAMBDA_TOL = 1e-12  # X's clipping factor (section 9)
DSR_MIN = 0.95
PBO_MAX = 0.25
DAY_US = 86_400_000_000
REASONS = ("switch", "re-cut", "limit", "stop", "unlock")
BOX = {p.name: (float(p.low), float(p.high)) for p in SPECS}
INSIDE, OUTSIDE = "inside the box", "outside the box"

NO_EDGE, INCONCLUSIVE, EDGE = "NO EDGE", "INCONCLUSIVE", "EDGE"
CANDIDATE, EDGE_NOT_CANDIDATE = "CANDIDATE FOR AUDIT", "EDGE, NOT A CANDIDATE"
NOT_TRIGGERED, STOP_DOES_NOT_HELP, STOP_HELPS = "NOT TRIGGERED", "STOP DOES NOT HELP", "STOP HELPS"
VERDICT_ORDER = (NO_EDGE, INCONCLUSIVE, EDGE)
HEADLINE_ORDER = (NO_EDGE, INCONCLUSIVE, EDGE_NOT_CANDIDATE, CANDIDATE)
STOP_OUTCOME_ORDER = (NO_EDGE, STOP_DOES_NOT_HELP, INCONCLUSIVE, STOP_HELPS)  # section 11A, among triggered
STOP_RUN_ORDER = (NOT_TRIGGERED, *STOP_OUTCOME_ORDER)  # stop rule 18 (module docstring)
TRIGGERS = ("a", "b", "c", "other, after the verdict")  # stop rule 18
CRITERIA = ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "P")
E5A_ITEMS = (
    "E1",
    "E2",
    "E3",
    "E4",
    "E6",
    "E7",
    "P",
    "G1",
    "G2",
    "G3",
    "G4",
    "G5(a)",
    "G6",
    "G7",
    "G8-excess",
)
SL_ITEMS = ("SL-E1", "SL-E2", "SL-B", "SL-E3", "SL-T", "SL-E4", "SL-E5", "SL-E6", "SL-E7", "SL-E8", "SL-P")
E7_ITEMS = ("E1", "E2", "E3", "E4")  # E7: each still holds without the best and the two best years (M20)
SL_E7_ITEMS = ("SL-E1", "SL-E2", "SL-E3", "SL-E4", "SL-T")  # SL-E7 (M15, M17, M20)
SL_E5_ITEMS = ("triggered", "SL-E1", "SL-E2", "SL-B", "SL-E3", "SL-T")  # SL-E5 (M15, M17)


def _count(value, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def _weekday(weekday) -> int | None:
    if weekday is None:
        return None
    if isinstance(weekday, bool) or not isinstance(weekday, numbers.Integral) or not 0 <= weekday <= 6:
        raise ValueError(
            f"weekday must be an integer in 0..6 (0 = Monday) or None (every close), got {weekday!r}"
        )
    return int(weekday)


def _rows_of(index: pd.DatetimeIndex, stamps) -> int:
    pos = index.get_indexer([pd.Timestamp(stamps)])[0]
    if pos < 0:
        raise ValueError(f"close {stamps} is not in the index")
    return int(pos)


# ------------------------------------------------------------------------------------------------ the signal


def sma(close, lookback, rows=None) -> np.ndarray:
    """SMA(t; L) = ``math.fsum(close[t - L + 1 .. t]) / L`` (close t included), computed per window; NaN before row
    L - 1. With ``rows``, only those rows are computed (the others are NaN): the values are the same either way."""
    x = np.asarray(close, dtype=float)
    if x.ndim != 1 or not (np.isfinite(x).all() and (x > 0).all()):
        raise ValueError("close must be a 1-D array of finite prices > 0")
    n_rows = _count(lookback, "lookback")
    n = len(x)
    out = np.full(n, np.nan)
    values = x.tolist()
    todo = range(n_rows - 1, n) if rows is None else np.asarray(rows, dtype=np.int64).tolist()
    for t in todo:
        if not 0 <= t < n:
            raise ValueError(f"row {t} is outside the {n} closes")
        if t >= n_rows - 1:
            out[t] = math.fsum(values[t - n_rows + 1 : t + 1]) / n_rows
    return out


def sma_distance(close, lookback, rows=None) -> np.ndarray:
    """m(t) = close(t) / SMA(t; L) - 1 (:func:`sma`); NaN where the average is not computed."""
    return np.asarray(close, dtype=float) / sma(close, lookback, rows) - 1.0


def activation(lookback) -> int:
    """A = max(R0, L - 1): the first row on which a check can change a state (section 4)."""
    return max(R0, _count(lookback, "lookback") - 1)


def check_closes(index, weekday=WEEKDAY, start_row: int = 0) -> np.ndarray:
    """The rows >= ``start_row`` whose close falls on ``weekday`` (``day_of_week``, 0 = Monday); ``weekday=None``
    means every close (the daily-check description). int64, increasing."""
    idx = pd.DatetimeIndex(index)
    day = _weekday(weekday)
    start = _count(start_row, "start_row", 0)
    rows = np.arange(len(idx), dtype=np.int64)
    keep = rows >= start
    if day is not None:
        keep &= idx.day_of_week.to_numpy() == day
    return rows[keep]


class TrendStates(NamedTuple):
    """Point-in-time trend states of one panel (section 4)."""

    z: np.ndarray  # (n, 2) int8, 1 = in: the state at close t, after the check at t (BTC, ETH)
    m: np.ndarray  # (n, 2) float: m at each check close, NaN elsewhere
    checks: np.ndarray  # int64 rows of the check closes (>= activation)
    activation: int


def _start_state(start) -> int:
    if start not in ("out", "in"):
        raise ValueError(
            f"start must be 'out' (the rule) or 'in' (the opposite-start description), got {start!r}"
        )
    return int(start == "in")


def _step(state: int, m: float, delta: float) -> int:
    if state == 0 and m > delta:
        return 1
    if state == 1 and m < -delta:
        return 0
    return state


def trend_states(bars: pd.DataFrame, lookback, buffer, *, weekday=WEEKDAY, start: str = "out") -> TrendStates:
    """The hysteresis states of BTC and ETH on a panel (module docstring). The state at close t depends on the
    closes 0..t only. ``start='in'`` is the opposite-start description only; the rule starts ``out``."""
    validate_panel(bars)
    n_rows = _count(lookback, "lookback")
    delta = _real(buffer, "buffer", 0.0, low_inclusive=True)
    first = _start_state(start)
    a_row = activation(n_rows)
    checks = check_closes(bars.index, weekday, a_row)
    n = len(bars)
    z = np.empty((n, len(ASSETS)), dtype=np.int8)
    m = np.full((n, len(ASSETS)), np.nan)
    for a, asset in enumerate(ASSETS):
        m[:, a] = sma_distance(bars[(asset, "close")].to_numpy(dtype=float), n_rows, rows=checks)
        state, last = first, 0
        for c in checks.tolist():
            z[last:c, a] = state
            state = _step(state, float(m[c, a]), delta)
            last = c
        z[last:, a] = state
    return TrendStates(z, m, checks, a_row)


class TrendStream:
    """The live trend state machine: fed one close at a time, it gives the states :func:`trend_states` gives on
    the panel of those closes, bit for bit (the same per-window ``math.fsum`` and comparisons)."""

    def __init__(self, lookback, buffer, *, weekday=WEEKDAY, start: str = "out"):
        self.lookback = _count(lookback, "lookback")
        self.buffer = _real(buffer, "buffer", 0.0, low_inclusive=True)
        self.weekday = _weekday(weekday)
        self.activation = activation(self.lookback)
        self._closes = [deque(maxlen=self.lookback) for _ in ASSETS]
        self._row = -1
        self._last: pd.Timestamp | None = None
        self.state = [_start_state(start)] * len(ASSETS)

    def update(self, ts, close_btc, close_eth) -> tuple[int, int]:
        """Add the close at ``ts`` (tz-aware, strictly after the previous one); returns (z_BTC, z_ETH) at it."""
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            raise ValueError(f"closes must be tz-aware (UTC close times), got {ts!r}")
        stamp = stamp.tz_convert("UTC")
        if self._last is not None and stamp <= self._last:
            raise ValueError(f"closes must be strictly increasing, got {ts!r} after {self._last!r}")
        prices = [_real(float(p), "close", 0.0, low_inclusive=False) for p in (close_btc, close_eth)]
        self._last = stamp
        self._row += 1
        for buf, price in zip(self._closes, prices, strict=True):
            buf.append(price)
        check = self._row >= self.activation and (self.weekday is None or stamp.day_of_week == self.weekday)
        if check:
            for a, (buf, price) in enumerate(zip(self._closes, prices, strict=True)):
                m = price / (math.fsum(list(buf)) / self.lookback) - 1.0
                self.state[a] = _step(self.state[a], m, self.buffer)
        return tuple(self.state)


# ------------------------------------------------------------------------------------------------ targets


def share_targets(share, f=F_SPLIT) -> tuple[float, float]:
    """The trend target of a coin in an uptrend: (s * f, s * (1 - f))."""
    s = _real(share, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    f = _real(f, "f", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    return s * f, s * (1.0 - f)


def _state_array(values, n: int, name: str) -> np.ndarray:
    a = np.asarray(values)
    if a.shape != (n, len(ASSETS)) or not np.isin(a, (0, 1)).all():
        raise ValueError(f"{name} must be a ({n}, 2) array of 0 and 1")
    return a.astype(np.int8)


def in_force(z, share, locks=None, *, f=F_SPLIT) -> np.ndarray:
    """The in-force targets e_a(t) = s(t) * (f, 1 - f)_a * [z_a(t) = in] * [a not locked at t], shape (n, 2).

    ``share`` is one s or one per row (R_0's schedule carries each fold's s)."""
    n = len(np.asarray(z))
    on = _state_array(z, n, "z").astype(bool)
    if locks is not None:
        on &= ~_state_array(locks, n, "locks").astype(bool)
    s = np.broadcast_to(np.asarray(share, dtype=float), (n,))
    if not (np.isfinite(s).all() and (s >= 0).all() and (s <= 1).all()):
        raise ValueError("crypto_share must be in [0, 1]")
    f = _real(f, "f", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    w = np.column_stack([s * f, s * (1.0 - f)])
    return np.where(on, w, 0.0)


def check_share(share, limits: Mapping, *, f=F_SPLIT) -> list[tuple[float, float]]:
    """Every target set of crypto share s (its 4 states) passes ``check_targets`` with the limits as read and
    :data:`HEADROOM` (stop rule 12), else ``ValueError`` naming s. Returns the 4 target sets."""
    min_cash, max_coin = _limit_values(limits)
    w_btc, w_eth = share_targets(share, f)
    sets = [(w_btc, w_eth), (w_btc, 0.0), (0.0, w_eth), (0.0, 0.0)]
    for a, b in sets:
        try:
            check_targets(a, b, min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM)
        except ValueError as exc:
            raise ValueError(
                f"check_share: crypto share {share!r} breaks the limits as read (stop rule 12): {exc}"
            ) from exc
    return sets


def check_feasibility(limits: Mapping, *, f=F_SPLIT) -> list[float]:
    """Stop rule 12 before any bar: :func:`check_share` for the box ends, every allowed value and the plateau
    extremes 0.24 and 0.72. Returns the shares checked (sorted)."""
    shares = sorted({*BOX["crypto_share"], *ALLOWED_S, *PLATEAU_SHARE_EXTREMES})
    for s in shares:
        check_share(s, limits, f=f)
    return shares


# ------------------------------------------------------------------------------------------------ the executor


def _target_array(targets, n: int) -> np.ndarray:
    a = np.array(targets, dtype=float)
    if a.shape != (n, len(ASSETS)) or not np.isfinite(a).all():
        raise ValueError(f"targets must be a finite ({n}, 2) array of target vectors")
    if (a < 0).any() or (a > 1).any() or (a.sum(axis=1) > 1).any():
        raise ValueError("every target must be in [0, 1] with w_BTC + w_ETH <= 1 (the rest is USDC)")
    return a


def _part(name: str, data: bytes) -> bytes:
    return name.encode() + b"\0" + len(data).to_bytes(8, "little") + data


def order_hash(result: pd.DataFrame) -> str:
    """SHA-256 of a :func:`run_states` result's orders: their close times (int64 microseconds, little-endian),
    reasons (newline-joined UTF-8) and target vectors (float64, little-endian, row-major)."""
    attrs = result.attrs
    orders = np.asarray(attrs["orders"], dtype=np.int64)
    digest = hashlib.sha256()
    digest.update(_part("closes", np.asarray(result.index.asi8[orders], dtype="<i8").tobytes()))
    digest.update(_part("reasons", "\n".join(str(r) for r in attrs["reasons"]).encode()))
    digest.update(_part("targets", np.asarray(attrs["order_targets"], dtype="<f8").tobytes()))
    return digest.hexdigest()


def state_hash(z, index) -> str:
    """SHA-256 of a state path: the close times (int64 microseconds) and the (n, 2) states (int8), little-endian."""
    idx = pd.DatetimeIndex(index)
    digest = hashlib.sha256()
    digest.update(_part("closes", np.asarray(idx.as_unit("us").asi8, dtype="<i8").tobytes()))
    digest.update(_part("z", _state_array(z, len(idx), "z").tobytes()))
    return digest.hexdigest()


def _previous(a: np.ndarray, t: int) -> np.ndarray:
    return a[t - 1] if t else np.zeros(a.shape[1], dtype=a.dtype)


def _reason(t: int, states: np.ndarray | None, locks: np.ndarray | None) -> str:
    if locks is not None and (locks[t] > _previous(locks, t)).any():
        return "stop"
    if states is not None and (states[t] != _previous(states, t)).any():
        return "switch"
    if locks is not None and (locks[t] < _previous(locks, t)).any():
        return "unlock"
    return "re-cut"


def run_states(
    bars: pd.DataFrame,
    targets,
    *,
    limits: Mapping,
    costs: Costs,
    states=None,
    locks=None,
) -> pd.DataFrame:
    """The one executor (module docstring). ``limits``: ``risk_limits("steady")``'s dict (both limits set);
    ``costs``: a :class:`Costs` built at run start. Every distinct target vector must pass ``check_targets`` with
    the limits and :data:`HEADROOM` before the run (stop rule 12), else ``ValueError``."""
    validate_panel(bars)
    if not isinstance(costs, Costs):
        raise ValueError(f"run_states: costs must be a Costs instance built at run start, got {costs!r}")
    min_cash, max_coin = _limit_values(limits)
    n = len(bars)
    tg = _target_array(targets, n)
    st = None if states is None else _state_array(states, n, "states")
    lk = None if locks is None else _state_array(locks, n, "locks")
    for w_btc, w_eth in np.unique(tg, axis=0).tolist():
        try:
            check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM)
        except ValueError as exc:
            raise ValueError(
                f"run_states: a target vector breaks the limits as read (stop rule 12): {exc}"
            ) from exc
    rows = [tuple(r) for r in tg.tolist()]
    zero = (0.0,) * len(ASSETS)
    breached = _breach_test(min_cash, max_coin)
    labels: dict[int, str] = {}

    def decide(t: int, w: tuple[float, ...]) -> tuple[float, ...] | None:
        vector = rows[t]
        if vector != (rows[t - 1] if t else zero):
            labels[t] = _reason(t, st, lk)
            return vector
        if breached(w):
            labels[t] = "limit"
            return vector
        return None

    result = _simulate(bars, costs, decide)
    orders = result.attrs["orders"]
    on = tg > 0.0
    changed = (on != np.vstack([np.zeros((1, len(ASSETS)), dtype=bool), on[:-1]])).sum(axis=1)
    result.attrs["targets"] = tg
    result.attrs["reasons"] = np.asarray([labels[t] for t in orders.tolist()], dtype=object)
    result.attrs["switches"] = changed[orders].astype(np.int64)
    result.attrs["order_targets"] = tg[orders]
    result.attrs["order_hash"] = order_hash(result)
    return result


# ------------------------------------------------------------------------------------------------ the BacktestFn

_PARAMS = frozenset({*PARAM_NAMES, "stop"})


def parse_params(params) -> dict:
    """Strict trend params: ``lookback`` (int >= 1), ``buffer`` (>= 0), ``crypto_share`` (in (0, 1]) and, for the
    stop-loss variant only, ``stop`` (phi in (0, 1); absent or None = no stop). Unknown or missing keys raise."""
    p = _check_params("trend", params, _PARAMS)
    stop = p.get("stop")
    return {
        "lookback": _param_int(p, "lookback"),
        "buffer": _param_float(p, "buffer", low=0.0, low_inclusive=True),
        "crypto_share": _param_float(
            p, "crypto_share", low=0.0, low_inclusive=False, high=1.0, high_inclusive=True
        ),
        "stop": None if stop is None else _param_float(p, "stop", low=0.0, low_inclusive=False, high=1.0),
    }


def trend_backtest(
    params: Mapping, bars: pd.DataFrame, *, limits: Mapping, costs: Costs, f=F_SPLIT, weekday=WEEKDAY
) -> pd.DataFrame:
    """The ``BacktestFn`` (section 4): the trend rule (with the stop when ``params`` holds ``stop``) on ``bars``
    from row 0. Bind ``limits`` and ``costs`` with ``functools.partial`` (picklable). ``weekday=None`` is the
    daily-check description."""
    p = parse_params(params)
    states = trend_states(bars, p["lookback"], p["buffer"], weekday=weekday)
    if p["stop"] is None:
        targets = in_force(states.z, p["crypto_share"], f=f)
        result = run_states(bars, targets, limits=limits, costs=costs, states=states.z)
    else:
        result, _ = stop_events(bars, states.z, p["crypto_share"], p["stop"], limits=limits, costs=costs, f=f)
    result.attrs["z"] = states.z
    result.attrs["checks"] = states.checks
    result.attrs["activation"] = states.activation
    result.attrs["state_hash"] = state_hash(states.z, bars.index)
    return result


# ------------------------------------------------------------------------------------------------ the stop


def _first_fall(ret, phi: float, start: int) -> int | None:
    value = np.cumprod(1.0 + np.asarray(ret, dtype=float))
    if start >= len(value):
        return None
    v = value[start:]
    fall = v / np.maximum.accumulate(v) - 1.0
    hit = np.flatnonzero(fall <= -phi)
    return start + int(hit[0]) if len(hit) else None


def _phi(phi) -> float:
    return _real(phi, "stop", 0.0, low_inclusive=False, high=1.0)


def recompute_stop_events(ret, phi) -> list[int]:
    """The stop events of a run, in one pass over its own ``ret`` (stop rule 13): V = cumprod(1 + ret); from the
    reference close (row 0, then the close after each event) the first close with V / H - 1 <= -phi."""
    phi = _phi(phi)
    events: list[int] = []
    while (nxt := _first_fall(ret, phi, events[-1] + 1 if events else 0)) is not None:
        events.append(nxt)
    return events


def lock_series(z, events: Iterable[int]) -> np.ndarray:
    """The locks (n, 2) of stop events on a state path: an event locks both coins from its close on; a coin is
    unlocked at the first close strictly after the latest event where its state turns from out to in."""
    n = len(np.asarray(z))
    states = _state_array(z, n, "z")
    at = sorted({_count(e, "event", 0) for e in events})
    if at and at[-1] >= n:
        raise ValueError(f"stop events must be rows of the {n}-row path, got {at[-1]}")
    marks = set(at)
    locks = np.zeros((n, len(ASSETS)), dtype=np.int8)
    locked = [0] * len(ASSETS)
    latest = -1
    for t in range(n):
        before = _previous(states, t)
        for a in range(len(ASSETS)):
            if locked[a] and t > latest and before[a] == 0 and states[t, a] == 1:
                locked[a] = 0
        if t in marks:
            locked = [1] * len(ASSETS)
            latest = t
        locks[t] = locked
    return locks


def stop_events(
    bars: pd.DataFrame, z, share, phi, *, limits: Mapping, costs: Costs, f=F_SPLIT
) -> tuple[pd.DataFrame, list[int]]:
    """The stop-loss variant by re-running (section 11A, "How it is computed"). Returns the last run and its
    events. attrs add ``stop`` (phi), ``stop_events``, ``stop_ordered`` (per event: an order was sent at its close),
    ``locks`` and ``passes`` (runs made: events + 1)."""
    phi = _phi(phi)
    n = len(bars)
    states = _state_array(z, n, "z")
    events: list[int] = []
    passes = 0
    while True:
        locks = lock_series(states, events)
        targets = in_force(states, share, locks, f=f)
        result = run_states(bars, targets, limits=limits, costs=costs, states=states, locks=locks)
        passes += 1
        nxt = _first_fall(result["ret"].to_numpy(dtype=float), phi, events[-1] + 1 if events else 0)
        if nxt is None:
            break
        events.append(nxt)
    sent = set(result.attrs["orders"].tolist())
    result.attrs["stop"] = phi
    result.attrs["stop_events"] = np.asarray(events, dtype=np.int64)
    result.attrs["stop_ordered"] = np.asarray([e in sent for e in events], dtype=bool)
    result.attrs["locks"] = locks
    result.attrs["passes"] = passes
    return result, events


def fresh_customer(
    bars: pd.DataFrame, z, share, phi, t0, *, limits: Mapping, costs: Costs, f=F_SPLIT
) -> tuple[pd.DataFrame, list[int]]:
    """The fresh-customer run of a fold (section 11A, M20): a book of ``costs.capital_usd`` (USD 10,000 with the
    run's cost model) in USDC at close t0, the high and the locks restarting there, the trend states computed from
    row 0 (``z`` on ``bars``). Close t0 orders its in-force targets, filled at the open of t0 + 1. Returns
    :func:`stop_events` on the rows t0 .. end."""
    p = _rows_of(bars.index, t0)
    states = _state_array(z, len(bars), "z")
    return stop_events(bars.iloc[p:], states[p:], share, phi, limits=limits, costs=costs, f=f)


# ------------------------------------------------------------------------------------------------ the harness


def train_grid() -> pd.DatetimeIndex:
    """The 2190 Kraken train closes as DATA.md counts them, with no prices: daily 2017-01-02 .. 2023-01-01, close
    2018-01-13 dropped (appendix B). UTC microseconds, named ``ts``."""
    days = pd.date_range("2017-01-02", "2023-01-01", freq="D", tz="UTC", name="ts").as_unit("us")
    return days.drop(pd.Timestamp("2018-01-13", tz="UTC"))


def fold_windows(
    index: pd.DatetimeIndex, *, warmup: int = WARMUP, fold_rows: int = FOLD_ROWS
) -> list[Window]:
    """The fold windows of ``walk_forward(len(index), fold_rows, fold_rows, expanding=True)`` in H0
    (``steady.fold_window(index, test, warmup)``): first_h120 = row 0 for warmup = 2190, t0, last."""
    folds = walk_forward(len(index), train_size=fold_rows, test_size=fold_rows, expanding=True)
    return [fold_window(index, fold.test, warmup=warmup) for fold in folds]


def _window(w) -> tuple[pd.Timestamp, pd.Timestamp]:
    if hasattr(w, "t0"):
        return pd.Timestamp(w.t0), pd.Timestamp(w.last)
    t0, last = w
    return pd.Timestamp(t0), pd.Timestamp(last)


def h0_slice(panel: pd.DataFrame, window, *, like: pd.DataFrame | None = None) -> pd.DataFrame:
    """Harness H0 (section 3, "Slicing"; section 7): the panel's rows from its OWN first close to ``window.last``
    (a close time from the Kraken panel), so every run starts at its panel's row 0 (Kraken 2017-01-02, Binance
    2017-08-18). The slice must end exactly at ``last`` and hold ``t0``; with ``like`` (the Kraken panel) its closes
    t0 .. last must be Kraken's. Otherwise ``steady.SliceMismatchError`` (the plan's "stop")."""
    validate_panel(panel)
    t0, last = _window(window)
    piece = panel.loc[:last]
    if len(piece) < 2 or piece.index[-1] != last or t0 not in piece.index:
        raise SliceMismatchError(f"the panel has no H0 slice that holds {t0} and ends at {last}")
    if like is not None and not piece.loc[t0:].index.equals(like.loc[t0:last].index):
        raise SliceMismatchError(
            f"the H0 slice's closes {t0} .. {last} are not the Kraken panel's (stop: PLAN.md section 3)"
        )
    return piece


class Schedule(NamedTuple):
    """S's own schedule over the out-of-sample span (section 9): the state pair and the crypto share at each of
    the W check closes c_k, the fold that holds each, and the rows before c_0 (common to every series)."""

    checks: np.ndarray  # (W,) span rows c_k, increasing
    z: np.ndarray  # (W, 2) int8: z(c_k), from the fold that holds c_k
    share: np.ndarray  # (W,) that fold's s
    fold: np.ndarray  # (W,) int64
    head_z: np.ndarray  # (c_0, 2) int8: fold 0's states on rows 0 .. c_0 - 1
    head_share: float  # fold 0's s


def _fold_rows(index: pd.DatetimeIndex, windows) -> list[tuple[int, int]]:
    spans = [(_rows_of(index, t0), _rows_of(index, last)) for t0, last in map(_window, windows)]
    if not spans:
        raise ValueError("windows must hold at least one fold")
    for i, (p0, pl) in enumerate(spans):
        if pl <= p0 or (i and p0 != spans[i - 1][1] + 1):
            raise ValueError(
                "fold windows must be contiguous: each t0 the close after the previous fold's last"
            )
    return spans


def stitched_schedule(
    index, windows, fold_states: Sequence, shares: Sequence, *, weekday=WEEKDAY
) -> Schedule:
    """R_0's schedule from S's fold runs (section 9). ``index``: the span (rows 0 .. the last fold's last close);
    ``windows``: each fold's (t0, last) (a ``steady.Window`` works); ``fold_states``: each fold's state path z on
    its H0 slice, rows 0 .. last_i (a prefix of the span); ``shares``: each fold's s. The check closes of fold i
    are its closes in [t0_i, last_i] on ``weekday``; z(c_k) and s come from that fold."""
    idx = pd.DatetimeIndex(index)
    spans = _fold_rows(idx, windows)
    if len(fold_states) != len(spans) or len(shares) != len(spans):
        raise ValueError("stitched_schedule: one state path and one share per fold")
    checks, zs, ss, folds = [], [], [], []
    for i, ((p0, pl), z, s) in enumerate(zip(spans, fold_states, shares, strict=True)):
        z = _state_array(z, pl + 1, f"fold {i} states")
        rows = check_closes(idx[: pl + 1], weekday, p0)
        checks.append(rows)
        zs.append(z[rows])
        ss.append(
            np.full(
                len(rows), _real(s, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
            )
        )
        folds.append(np.full(len(rows), i, dtype=np.int64))
    if not len(checks[0]):
        raise ValueError("stitched_schedule: fold 0 must hold the first check close")
    first = int(checks[0][0])
    head = _state_array(fold_states[0], spans[0][1] + 1, "fold 0 states")[:first]
    return Schedule(
        np.concatenate(checks),
        np.vstack(zs).astype(np.int8),
        np.concatenate(ss),
        np.concatenate(folds),
        head,
        float(ss[0][0]),
    )


def shifted(schedule: Schedule, u: int) -> Schedule:
    """B3: z_u(c_k) = z(c_((k + u) mod W)), both coins together, each entry carrying its fold's s (section 9). The
    rows before c_0 are unchanged; no price is read."""
    w = len(schedule.checks)
    u = _count(u, "u", 0)
    if u >= w:
        raise ValueError(f"u must be in 0..{w - 1}, got {u}")
    order = (np.arange(w) + u) % w
    return schedule._replace(z=schedule.z[order], share=schedule.share[order], fold=schedule.fold[order])


def span_targets(schedule: Schedule, n: int, *, f=F_SPLIT) -> tuple[np.ndarray, np.ndarray]:
    """The per-row trend targets v and states z of a schedule on an n-row span: fold 0's before c_0, then the entry
    of the latest check close c_k <= t (held between check closes)."""
    checks = schedule.checks
    n = _count(n, "n")
    first = int(checks[0])
    if int(checks[-1]) >= n or len(schedule.head_z) != first:
        raise ValueError("span_targets: the schedule does not fit the span")
    latest = np.searchsorted(checks, np.arange(first, n), side="right") - 1
    z = np.vstack([schedule.head_z, schedule.z[latest]]).astype(np.int8)
    share = np.concatenate([np.full(first, schedule.head_share), schedule.share[latest]])
    return in_force(z, share, f=f), z


def guarded_offsets(w: int, guard: int = LEAD_GUARD) -> np.ndarray:
    """The null's offsets u = G + 1 .. W - 1 (section 9); a span with W <= G + 1 raises."""
    w, guard = _count(w, "W"), _count(guard, "guard", 0)
    if w <= guard + 1:
        raise ValueError(f"a span of W = {w} check closes leaves no shift beyond the lead guard G = {guard}")
    return np.arange(guard + 1, w, dtype=np.int64)


def lead_offsets(w: int, guard: int = LEAD_GUARD) -> np.ndarray:
    """B3-lead: u = 1 .. G (descriptions only, never a null)."""
    guarded_offsets(w, guard)
    return np.arange(1, guard + 1, dtype=np.int64)


def lag_offsets(w: int, guard: int = LEAD_GUARD) -> np.ndarray:
    """The delays of 1 .. G weeks, u = W - G .. W - 1 (in E1's null; R_0's rank among them is a description)."""
    guarded_offsets(w, guard)
    return np.arange(w - guard, w, dtype=np.int64)


def segment_source_rows(index, checks, u: int) -> np.ndarray:
    """The source row of each row of the weekly-segment shift by u (section 11A; module docstring): a row at
    calendar offset j after c_k takes the latest row of segment (k + u) mod W whose offset is at most j."""
    times = pd.DatetimeIndex(index).asi8
    n = len(times)
    c = np.asarray(checks, dtype=np.int64)
    w = len(c)
    u = _count(u, "u", 0)
    if not w or c[-1] > n - 2 or (np.diff(c) <= 0).any() or c[0] < 0:
        raise ValueError(
            "segment_source_rows: check closes must be increasing rows before the last close but one"
        )
    if u >= w:
        raise ValueError(f"u must be in 0..{w - 1}, got {u}")
    ends = np.append(c[1:], n - 1)
    src = np.arange(n, dtype=np.int64)
    for k in range(w):
        kk = (k + u) % w
        rows = np.arange(c[k], ends[k])
        pool = np.arange(c[kk], ends[kk])
        offsets = times[pool] - times[c[kk]]
        src[rows] = pool[np.searchsorted(offsets, times[rows] - times[c[k]], side="right") - 1]
    src[n - 1] = src[n - 2]
    return src


def segment_shift(series, index, checks, u: int) -> np.ndarray:
    """``series`` (one entry per row) moved by the weekly-segment shift u (:func:`segment_source_rows`)."""
    a = np.asarray(series)
    if len(a) != len(index):
        raise ValueError("segment_shift: one entry per row of the index")
    return a[segment_source_rows(index, checks, u)]


def stitched_locks(index, windows, fold_locks: Sequence) -> np.ndarray:
    """R_0^phi's lock pairs l(t) (section 11A): fold 0's on rows 0 .. last_0, fold i's on its test rows
    t0_i .. last_i. ``fold_locks``: each fold's S^phi locks on rows 0 .. last_i."""
    idx = pd.DatetimeIndex(index)
    spans = _fold_rows(idx, windows)
    if len(fold_locks) != len(spans) or spans[-1][1] != len(idx) - 1:
        raise ValueError(
            "stitched_locks: one lock path per fold, and the span ends at the last fold's last close"
        )
    out = np.zeros((len(idx), len(ASSETS)), dtype=np.int8)
    for i, ((p0, pl), lk) in enumerate(zip(spans, fold_locks, strict=True)):
        lk = _state_array(lk, pl + 1, f"fold {i} locks")
        start = 0 if i == 0 else p0
        out[start : pl + 1] = lk[start : pl + 1]
    return out


def run_span(
    bars: pd.DataFrame,
    schedule: Schedule,
    *,
    limits: Mapping,
    costs: Costs,
    f=F_SPLIT,
    u: int = 0,
    locks=None,
    placebo: bool = False,
) -> pd.DataFrame:
    """R_0 and its shifts, one book from row 0 (H0) through the one executor (sections 9 and 11A).

    - ``locks=None``: the plain schedule shifted by u (:func:`shifted`; u = 0 is R_0).
    - ``locks`` (the stitched lock pairs, :func:`stitched_locks`): R_0^phi's entries E = v * (1 - l); u = 0 is
      R_0^phi, u > 0 its weekly-segment shift (:func:`segment_shift` of E, the states and the locks).
    - ``placebo=True`` (with ``locks``): the placebo stop u, E_u = v * (1 - segment_shift(l, u)), the trend part kept.
    """
    n = len(bars)
    if locks is None:
        if placebo:
            raise ValueError("run_span: placebo stops need the locks")
        v, z = span_targets(shifted(schedule, u), n, f=f)
        return run_states(bars, v, limits=limits, costs=costs, states=z)
    v, z = span_targets(schedule, n, f=f)
    lk = _state_array(locks, n, "locks")
    if placebo:
        lu = segment_shift(lk, bars.index, schedule.checks, u)
        return run_states(
            bars, np.where(lu.astype(bool), 0.0, v), limits=limits, costs=costs, states=z, locks=lu
        )
    entries = np.where(lk.astype(bool), 0.0, v)
    if u:
        src = segment_source_rows(bars.index, schedule.checks, u)
        entries, z, lk = entries[src], z[src], lk[src]
    return run_states(bars, entries, limits=limits, costs=costs, states=z, locks=lk)


def placebo_stops(v, locks, index, checks, u: int) -> tuple[np.ndarray, np.ndarray]:
    """The placebo stop u's in-force targets E_u = v * (1 - l_u) and its locks l_u = segment_shift(l, u)."""
    n = len(index)
    lu = segment_shift(_state_array(locks, n, "locks"), index, checks, u)
    tv = _target_array(v, n)
    return np.where(lu.astype(bool), 0.0, tv), lu


def same_book_at(a: pd.DataFrame, b: pd.DataFrame, t0) -> bool:
    """True when two runs from row 0 hold the same book at close ``t0`` bit for bit (stop rule 14): the same closes
    up to and including ``t0`` and, on those rows, equal ``ret``, ``turnover``, ``cost`` and both weights (so the
    same value and coin units). The runs may end at different closes (S's fold run and R_0's span)."""
    cols = ["ret", "turnover", "cost", *WEIGHT_COLUMNS]
    p, q = _rows_of(a.index, t0), _rows_of(b.index, t0)
    if p != q or not a.index[: p + 1].equals(b.index[: q + 1]):
        return False
    return bool(np.array_equal(a[cols].to_numpy()[: p + 1], b[cols].to_numpy()[: p + 1]))


# ------------------------------------------------------------------------------------------------ comparators


def from_t0(
    bars: pd.DataFrame,
    base_targets,
    t0,
    target,
    *,
    limits: Mapping,
    costs: Costs,
    base_states=None,
    target_state=None,
) -> pd.DataFrame:
    """A comparator with S's start (section 7, common start): S's in-force targets on rows before ``t0``, then
    ``target`` from close ``t0`` on (an order at t0 unless S's vector at t0 - 1 is already it), then limit fixes."""
    n = len(bars)
    tg = _target_array(base_targets, n)
    p = _rows_of(bars.index, t0)
    tg[p:] = np.asarray(target, dtype=float)
    states = None
    if base_states is not None:
        if target_state is None:
            raise ValueError("from_t0: base_states needs the target_state that labels the rows from t0 on")
        states = _state_array(base_states, n, "base_states").copy()
        states[p:] = np.asarray(target_state, dtype=np.int8)
    return run_states(bars, tg, limits=limits, costs=costs, states=states)


def always_in_n0(
    bars: pd.DataFrame, base_targets, t0, share, *, limits: Mapping, costs: Costs, f=F_SPLIT, base_states=None
) -> pd.DataFrame:
    """N0: from S's book at close t0, the states forced to (in, in): it orders (s f, s (1 - f)) at t0 unless S
    already holds it, then limit fixes only (section 9). For N0^phi pass S^phi's targets (no stop is run)."""
    return from_t0(
        bars,
        base_targets,
        t0,
        share_targets(share, f),
        limits=limits,
        costs=costs,
        base_states=base_states,
        target_state=(1, 1),
    )


def exposure_target(result: pd.DataFrame, t0, *, limits: Mapping) -> dict:
    """X's targets (section 9): e = the mean (``math.fsum`` / count) of S's w_BTC and w_ETH over the kept closes
    after t0. If e fails ``check_targets`` with the limits and :data:`HEADROOM`, both are scaled by the largest
    common lambda < 1 that passes (bisection to :data:`LAMBDA_TOL`) and marked clipped. Returns ``target``,
    ``mean``, ``clipped`` and ``lambda``."""
    min_cash, max_coin = _limit_values(limits)
    kept = result.loc[pd.Timestamp(t0) :].iloc[1:]
    if not len(kept):
        raise ValueError("exposure_target: no kept close after t0")
    mean = tuple(math.fsum(kept[col].tolist()) / len(kept) for col in WEIGHT_COLUMNS)

    def passes(lam: float) -> bool:
        try:
            check_targets(
                lam * mean[0], lam * mean[1], min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM
            )
        except ValueError:
            return False
        return True

    if passes(1.0):
        return {"target": mean, "mean": mean, "clipped": False, "lambda": 1.0}
    if not passes(0.0):
        raise ValueError("exposure_target: the limits refuse even an all-cash book")
    low, high = 0.0, 1.0
    while high - low > LAMBDA_TOL:
        mid = (low + high) / 2.0
        if passes(mid):
            low = mid
        else:
            high = mid
    return {"target": (low * mean[0], low * mean[1]), "mean": mean, "clipped": True, "lambda": low}


def exposure_x(
    bars: pd.DataFrame, result: pd.DataFrame, t0, *, limits: Mapping, costs: Costs
) -> tuple[pd.DataFrame, dict]:
    """X (or X^phi from S^phi's run): :func:`exposure_target`'s targets from S's book at close t0, ordered at t0,
    then limit fixes only. Returns the run and the target info."""
    info = exposure_target(result, t0, limits=limits)
    run = from_t0(bars, result.attrs["targets"], t0, info["target"], limits=limits, costs=costs)
    return run, info


# ------------------------------------------------------------------------------------------------ G5 plateau


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def plateau_step(params: Mapping, name: str, factor) -> tuple[dict, str]:
    """One G5 step (section 10): ``lookback`` down = max(1, min(half_up(0.8 L), L - 1)), up = max(half_up(1.2 L),
    L + 1); ``buffer`` and ``crypto_share`` times the factor, not rounded. The mark is :data:`OUTSIDE` when the
    stepped value leaves the search box, else :data:`INSIDE`."""
    p = parse_params(params)
    if name not in PARAM_NAMES:
        raise ValueError(f"plateau_step: name must be one of {PARAM_NAMES}, got {name!r}")
    factor = _real(factor, "factor", 0.0, low_inclusive=False)
    if factor == 1.0:
        raise ValueError("plateau_step: factor must not be 1")
    value = p[name]
    if name == "lookback":
        new = (
            max(1, min(_half_up(factor * value), value - 1))
            if factor < 1
            else max(_half_up(factor * value), value + 1)
        )
    else:
        new = value * factor
    low, high = BOX[name]
    out = {k: v for k, v in p.items() if k != "stop" or v is not None}
    out[name] = new
    return out, INSIDE if low <= new <= high else OUTSIDE


def plateau_steps(chosen: Sequence[Mapping], limits: Mapping, *, f=F_SPLIT) -> list[dict]:
    """The 6 G5 steps (lookback, buffer, crypto_share, each x0.8 then x1.2), each applied to every entry of
    ``chosen`` at once (G5(a): every fold's choice; G5(b): ``[default]``). Every stepped s passes
    :func:`check_share` (stop rule 12). Each step: ``param``, ``factor``, ``params`` (per entry), ``marks`` and
    ``mark`` (:data:`OUTSIDE` if any entry is outside the box)."""
    if not chosen:
        raise ValueError("plateau_steps: chosen must hold at least one parameter set")
    steps = []
    for name in PARAM_NAMES:
        for factor in PLATEAU_FACTORS:
            pairs = [plateau_step(p, name, factor) for p in chosen]
            for params, _ in pairs:
                check_share(params["crypto_share"], limits, f=f)
            marks = [m for _, m in pairs]
            steps.append(
                {
                    "param": name,
                    "factor": factor,
                    "params": [p for p, _ in pairs],
                    "marks": marks,
                    "mark": OUTSIDE if OUTSIDE in marks else INSIDE,
                }
            )
    return steps


def keeps_share(sharpe_s: float, others: Iterable[float], keep: float = PLATEAU_KEEP) -> bool:
    """G5 and E5(b): Sharpe(S) > 0 and every other Sharpe >= keep x Sharpe(S) (a NaN anywhere fails)."""
    others = list(others)
    return bool(sharpe_s > 0 and all(x >= keep * sharpe_s for x in others))


# ------------------------------------------------------------------------------------------------ criteria


def rank_holds(rank_p: float) -> bool:
    """The one decision rule of E1, E7's E1, E8, SL-E1, SL-E7, SL-E8, SL-T, the calibration and A0 (M16): the rank
    p = (1 + #{shifts at or above}) / (shifts + 1) < 0.05 (``steady.e1_rank(...)["rank_p"]``)."""
    return bool(rank_p < ALPHA)


def guarded(shifts: Mapping[int, object], w: int, guard: int = LEAD_GUARD) -> list:
    """The series of the guarded offsets u = G + 1 .. W - 1, in that order; lead offsets are never read."""
    out = []
    for u in guarded_offsets(w, guard).tolist():
        if u not in shifts:
            raise ValueError(f"guarded: the series of offset u = {u} is missing")
        out.append(shifts[u])
    return out


def e1_test(r0, shifts: Mapping[int, object], w: int, *, keep=None, guard: int = LEAD_GUARD) -> dict:
    """E1 (and E7's E1, E8, SL-E1, SL-T): R_0's Sharpe against its guarded shifts, ``steady.e1_rank`` on the rows
    ``keep`` (a boolean mask; all rows by default). Returns e1_rank's numbers, ``n_shifts``, ``at_or_above``,
    ``holds`` (:func:`rank_holds`) and ``p95_holds`` (e1_rank's ``holds``, a description)."""
    r = np.asarray(r0, dtype=float)
    mask = np.ones(len(r), dtype=bool) if keep is None else np.asarray(keep, dtype=bool)
    if mask.shape != r.shape:
        raise ValueError("e1_test: keep must be one flag per row")
    matrix = np.vstack([np.asarray(x, dtype=float)[mask] for x in guarded(shifts, w, guard)])
    rank = e1_rank(r[mask], matrix)
    return {
        **rank,
        "n_shifts": len(matrix),
        "at_or_above": int(np.sum(rank["draw_sharpes"] >= rank["sharpe"])),
        "holds": rank_holds(rank["rank_p"]),
        "p95_holds": rank["holds"],
    }


def e2_holds(d: float, p: float) -> bool:
    """E2's rule: D > 0 and the paired bootstrap's p < 0.05 (``steady.paired_bootstrap``'s ``holds``)."""
    return bool(d > 0.0 and p < ALPHA)


def e2_test(
    s: pd.Series, n0: pd.Series, *, mean_block: float = E2_MEAN_BLOCK, n_resamples: int = E2_RESAMPLES
):
    """E2 (and SL-E2): ``steady.paired_bootstrap(S, N0, n_resamples=10000, mean_block=60, seed=0)``, with
    ``holds`` by :func:`e2_holds`."""
    out = paired_bootstrap(s, n0, n_resamples=n_resamples, mean_block=mean_block, seed=0)
    return {**out, "holds": e2_holds(out["d"], out["p"])}


def e3_holds(dd_s: float, p5_s: float, dd_x: float, p5_x: float) -> bool:
    """E3 (and SL-E3): the historical max drawdown and G6's statistic both strictly shallower (less negative)."""
    return bool(dd_s > dd_x and p5_s > p5_x)


def g6_statistic(returns) -> float:
    """G6's statistic: the p5 of 1000 stationary block-bootstrap max drawdowns, mean block 20, seed 0, exactly as
    ``overfitting_report`` computes ``mc_drawdown_worst5pct``."""
    draws = mc.block_bootstrap_drawdowns(
        np.asarray(returns, dtype=float), mean_block=MC_MEAN_BLOCK, n_sims=MC_SIMS
    )
    return mc.percentiles(draws, (5,))["p5"]


def g6_holds(p5: float, budget: float | None) -> bool:
    """G6: p5 >= -budget, with the budget recorded before any bar; a MISSING budget (None) fails."""
    return bool(budget is not None and p5 >= -budget)


def g8_excess_pass(split: Mapping) -> bool:
    """G8-excess (section 10): on ``steady.regime_split(S, table, benchmark=N0)``, excess_total > 0 and every
    regime's excess <= excess_total / 2."""
    if "excess" not in split or "excess_total" not in split:
        raise ValueError("g8_excess_pass: the split needs the N0 benchmark (excess and excess_total)")
    total = split["excess_total"]
    return bool(total > 0.0 and all(x <= total / 2.0 for x in split["excess"].values()))


def bar_years(index) -> np.ndarray:
    """The calendar year of each bar: its close time minus 1 day (section 11)."""
    return (pd.DatetimeIndex(index) - pd.Timedelta(days=1)).year.to_numpy()


def loyo(s_returns: pd.Series, n0_returns: pd.Series) -> dict:
    """E6: Delta_y = fsum over bar-year y's rows of ln(1 + S) - ln(1 + N0), Delta = fsum of the Delta_y; holds if
    Delta > 0 and Delta - Delta_y > 0 for every year present."""
    if not (
        isinstance(s_returns, pd.Series) and isinstance(n0_returns, pd.Series)
    ) or not s_returns.index.equals(n0_returns.index):
        raise ValueError("loyo: S and N0 must be Series on the same kept closes")
    diff = np.log1p(s_returns.to_numpy(dtype=float)) - np.log1p(n0_returns.to_numpy(dtype=float))
    years = bar_years(s_returns.index)
    delta_y = {int(y): math.fsum(diff[years == y].tolist()) for y in sorted(set(years.tolist()))}
    delta = math.fsum(delta_y.values())
    return {
        "delta_y": delta_y,
        "delta": delta,
        "holds": bool(delta > 0.0 and all(delta - d > 0.0 for d in delta_y.values())),
    }


def year_returns(btc_close: pd.Series, kept) -> dict[int, float]:
    """BTC's compounded close-to-close return over each bar-year's kept rows (E7): per kept row r = close / the
    previous panel close - 1, multiplied in time order."""
    idx = pd.DatetimeIndex(kept)
    pos = btc_close.index.get_indexer(idx)
    if not idx.is_monotonic_increasing or idx.has_duplicates or (pos < 1).any():
        raise ValueError(
            "year_returns: kept must be strictly increasing panel closes, none of them the first"
        )
    close = btc_close.to_numpy(dtype=float)
    growth: dict[int, float] = {}
    for y, r in zip(bar_years(idx).tolist(), (close[pos] / close[pos - 1] - 1.0).tolist(), strict=True):
        growth[y] = growth.get(y, 1.0) * (1.0 + r)
    return {y: g - 1.0 for y, g in growth.items()}


def boom_years(btc_close: pd.Series, kept) -> list[int]:
    """The bar-years ranked by :func:`year_returns`, best first; a tie goes to the earlier year (E7)."""
    ret = year_returns(btc_close, kept)
    return sorted(ret, key=lambda y: (-ret[y], y))


def without_years(kept, years: Iterable[int]) -> np.ndarray:
    """The kept rows whose bar-year is not in ``years`` (a boolean mask, time order kept)."""
    return ~np.isin(bar_years(kept), list(years))


def e5a_holds(a: Mapping, b: Mapping, sharpe_a: float, sharpe_b: float) -> dict:
    """E5(a): seeds A and B give the same outcome (True, or not True: a MISSING fails) for each of
    :data:`E5A_ITEMS`, the gates measured at S only (M12), and their OOS Sharpes differ by <= 0.25. Other keys
    (grid steps, the default, S(s_k)) are ignored."""
    differ = [k for k in E5A_ITEMS if (a.get(k) is True) != (b.get(k) is True)]
    close = bool(abs(sharpe_a - sharpe_b) <= SEED_SHARPE_GAP)
    return {"differ": differ, "sharpes_close": close, "holds": not differ and close}


def e9_holds(sharpe_theta: float, sharpe_s: float, sharpe_n0: float, shift_sharpes: Sequence[float]) -> bool:
    """E9 (section 11): Sharpe > 0, >= 0.5 x Sharpe(S), >= 0.5 x Sharpe(N0 on validate) and > the median of its
    guarded validate shifts (pass :func:`guarded`'s series' Sharpes)."""
    shifts = np.asarray(shift_sharpes, dtype=float)
    if not len(shifts):
        raise ValueError("e9_holds: no shift Sharpes")
    return bool(
        sharpe_theta > 0
        and sharpe_theta >= 0.5 * sharpe_s
        and sharpe_theta >= 0.5 * sharpe_n0
        and sharpe_theta > float(np.median(shifts))
    )


def power_count(fold_states: Sequence, windows, index) -> dict:
    """P (section 11): coin-state changes (both coins counted) at check closes c whose orders fill in the fold's
    kept rows (t0_i <= c <= last_i - 1), first buys excluded (module docstring). Holds if the total is >= 20 with
    at least one change in each of at least 4 folds. Also ``switch_weeks`` (distinct closes with a counted change)
    and ``out_spells`` per coin (counted out -> in changes), descriptions."""
    idx = pd.DatetimeIndex(index)
    spans = _fold_rows(idx, windows)
    if len(fold_states) != len(spans):
        raise ValueError("power_count: one state path per fold")
    per_fold, weeks, spells = [], set(), [0] * len(ASSETS)
    for i, ((p0, pl), z) in enumerate(zip(spans, fold_states, strict=True)):
        z = _state_array(z, pl + 1, f"fold {i} states").astype(int)
        prev = np.vstack([np.zeros((1, len(ASSETS)), dtype=int), z[:-1]])
        count = 0
        for a in range(len(ASSETS)):
            rows = np.flatnonzero(z[:, a] != prev[:, a])
            counted = [t for t in rows[1:].tolist() if p0 <= t <= pl - 1]
            count += len(counted)
            weeks.update(int(idx[t].value) for t in counted)
            spells[a] += sum(1 for t in counted if z[t, a] == 1)
        per_fold.append(count)
    total = sum(per_fold)
    folds_with = sum(1 for c in per_fold if c >= 1)
    return {
        "per_fold": per_fold,
        "total": total,
        "folds_with": folds_with,
        "holds": bool(total >= MIN_SWITCHES and folds_with >= MIN_SWITCH_FOLDS),
        "switch_weeks": len(weeks),
        "out_spells": dict(zip(ASSETS, spells, strict=True)),
    }


# ------------------------------------------------------------------------------------------------ orders in time


def order_log(result: pd.DataFrame, t0=None) -> pd.DataFrame:
    """One row per fill row of a :func:`run_states` result (rows with turnover > 0; with ``t0``, the kept rows after
    t0 only): ``filled`` (its close), ``decided`` (the order's close), ``reason``, ``switches`` (in-force coin
    changes) and ``legs`` (legs traded)."""
    attrs = result.attrs
    orders = attrs["orders"].tolist()
    at = {t: i for i, t in enumerate(orders)}
    rows = np.flatnonzero(result["turnover"].to_numpy() > 0.0)
    legs = attrs["fills"]["bar"].value_counts()
    if any(r - 1 not in at for r in rows.tolist()):
        raise ValueError("order_log: a fill row without an order at the close before it")
    log = pd.DataFrame(
        {
            "filled": result.index[rows],
            "decided": result.index[rows - 1],
            "reason": np.asarray([attrs["reasons"][at[r - 1]] for r in rows.tolist()], dtype=object),
            "switches": np.asarray([attrs["switches"][at[r - 1]] for r in rows.tolist()], dtype=np.int64),
            "legs": np.asarray([int(legs.get(r, 0)) for r in rows.tolist()], dtype=np.int64),
        }
    )
    return log if t0 is None else log[log["filled"] > pd.Timestamp(t0)].reset_index(drop=True)


def rolling_count(times, kept, weights=None, days: int = WINDOW_DAYS) -> np.ndarray:
    """For each kept close t, the sum of ``weights`` (1 each by default) of the ``times`` in (t - days, t]."""
    stamps = pd.DatetimeIndex(times).asi8
    w = np.ones(len(stamps)) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != stamps.shape:
        raise ValueError("rolling_count: one weight per time")
    order = np.argsort(stamps, kind="stable")
    stamps, w = stamps[order], w[order]
    ends = pd.DatetimeIndex(kept).asi8
    days = _count(days, "days")
    cum = np.concatenate([[0.0], np.cumsum(w)])
    hi = np.searchsorted(stamps, ends, side="right")
    lo = np.searchsorted(stamps, ends - days * DAY_US, side="right")
    return cum[hi] - cum[lo]


def rolling_order_count(log: pd.DataFrame, kept, days: int = WINDOW_DAYS) -> np.ndarray:
    """R1's count: orders filled in (t - 30 days, t] for each kept close t (``log`` from :func:`order_log`)."""
    return rolling_count(log["filled"], kept, days=days)


def covered_days(index, kept) -> float:
    """The calendar days the kept rows cover: the sum over kept rows of (close - the previous panel close)."""
    idx = pd.DatetimeIndex(index)
    pos = idx.get_indexer(pd.DatetimeIndex(kept))
    if (pos < 1).any():
        raise ValueError("covered_days: kept must be panel closes, none of them the first")
    return float((idx.asi8[pos] - idx.asi8[pos - 1]).sum() / DAY_US)


def r1_check(log: pd.DataFrame, kept, days_covered: float) -> dict:
    """R1, "a few trades a month" (section 12): mean = 30 x orders filled in kept rows / ``days_covered`` <= 2 and
    the most in any 30 days (:func:`rolling_order_count`) <= 5."""
    kept = pd.DatetimeIndex(kept)
    n = int(np.isin(pd.DatetimeIndex(log["filled"]).asi8, kept.asi8).sum())
    mean = WINDOW_DAYS * n / _real(days_covered, "days_covered", 0.0, low_inclusive=False)
    most = int(rolling_order_count(log, kept).max(initial=0.0))
    return {"orders": n, "mean": mean, "most": most, "holds": bool(mean <= R1_MEAN and most <= R1_MOST)}


def trade_frequency(log: pd.DataFrame, kept) -> dict:
    """The trade-frequency table (section 16, M3): per kept close, the state switches, fills and legs whose fill
    rows fall in the 30 days ending at it; ``median`` and ``worst`` of each over ``kept``."""
    out = {}
    for name, weights in (("switches", log["switches"]), ("fills", None), ("legs", log["legs"])):
        counts = rolling_count(log["filled"], kept, weights)
        out[name] = {"median": float(np.median(counts)), "worst": float(counts.max())}
    return out


# ------------------------------------------------------------------------------------------------ luck statistics


def _active_matrices(studies: Iterable[str], out_dir: str | Path, first_row: int) -> list[np.ndarray]:
    first_row = _count(first_row, "first_row", 0)
    out = []
    for study in studies:
        m = load_trial_returns(study, out_dir).iloc[first_row:].dropna()
        if m.shape[1] >= 2:
            out.append(m.to_numpy(dtype=float))
    return out


def active_stats(
    matrices: Sequence, *, oos_returns=None, n_raw: float | None = None, n_strict: float | None = None
) -> dict:
    """The luck statistics of trial matrices (rows = periods, columns = trials), exactly as ``overfitting_report``
    computes them: trial Sharpes ``stats.sharpe`` per column, the effective count summed over matrices, each
    matrix's PBO (``n_blocks=10``) and its mean, and with ``oos_returns`` the DSR at the effective, raw and strict
    counts (NaN when no matrix has 2+ trials or a count is not given)."""
    trial_sharpes: list[float] = []
    eff, pbos, logits = [], [], []
    for m in matrices:
        frame = pd.DataFrame(np.asarray(m, dtype=float))
        trial_sharpes += [stats.sharpe(frame[c]) for c in frame.columns]
        eff.append(stats.effective_trials(frame.to_numpy()))
        result = stats.probability_of_backtest_overfitting(frame.to_numpy(), n_blocks=10)
        pbos.append(result["pbo"])
        logits.append(np.asarray(result["logits"], dtype=float))
    n_eff = float(np.sum(eff)) if eff else 1.0
    out = {
        "trial_sharpes": trial_sharpes,
        "trials_effective": n_eff,
        "pbo_per_study": pbos,
        "logits_per_study": logits,
        "pbo_mean": float(np.mean(pbos)) if pbos else math.nan,
    }
    oos = None if oos_returns is None else np.asarray(oos_returns, dtype=float)
    for key, count in (("dsr_effective", n_eff), ("dsr_raw", n_raw), ("dsr_strict", n_strict)):
        ok = bool(trial_sharpes) and oos is not None and count is not None
        out[key] = stats.deflated_sharpe_ratio(oos, trial_sharpes, n_trials=count)["dsr"] if ok else math.nan
    return out


def active_report(
    studies: Iterable[str],
    out_dir: str | Path,
    first_row: int = FIRST_ACTIVE_ROW,
    *,
    oos_returns=None,
    n_raw: float | None = None,
    n_strict: float | None = None,
) -> dict:
    """The active-row reading (section 14): every study's completed trials cut to rows ``first_row`` .. end
    (``load_trial_returns(...).iloc[first_row:].dropna()``; studies with fewer than 2 trials skipped), then
    :func:`active_stats`. With ``first_row=0`` it equals ``overfitting_report``'s numbers bit for bit."""
    return active_stats(
        _active_matrices(studies, out_dir, first_row), oos_returns=oos_returns, n_raw=n_raw, n_strict=n_strict
    )


def g3_g4(rep: Mapping, active: Mapping) -> dict:
    """G3 and G4 in both readings (section 10): DSR (effective) >= 0.95 in ``overfitting_report`` and on the
    active rows; PBO mean <= 0.25 in both. A NaN fails."""
    return {
        "G3": bool(rep["dsr_effective_count"] >= DSR_MIN and active["dsr_effective"] >= DSR_MIN),
        "G4": bool(rep["pbo_mean"] <= PBO_MAX and active["pbo_mean"] <= PBO_MAX),
    }


# ------------------------------------------------------------------------------------------------ verdicts


def _ok(results: Mapping, key) -> bool:
    return results.get(key) is True


def verdict(criteria: Mapping, *, stopped: bool = False, switches: int | None = None) -> dict:
    """The mechanical verdict (section 12): NO EDGE if E1 or E2 fails ("(LOW POWER: k switches)" when P fails too);
    INCONCLUSIVE if P or any of E3-E8 fails, a stop rule ended the study, or E9 (when given) fails; else EDGE. A
    MISSING (not True) criterion fails. ``look_earned``: E1-E8 and P hold and no stop rule fired."""
    if not (_ok(criteria, "E1") and _ok(criteria, "E2")):
        base = NO_EDGE
        label = base if _ok(criteria, "P") else f"{base} (LOW POWER: {switches} switches)"
    elif (
        stopped
        or not all(_ok(criteria, k) for k in CRITERIA)
        or ("E9" in criteria and not _ok(criteria, "E9"))
    ):
        base = label = INCONCLUSIVE
    else:
        base = label = EDGE
    earned = not stopped and all(_ok(criteria, k) for k in CRITERIA)
    return {"verdict": base, "label": label, "look_earned": earned}


def _s(s: float) -> str:
    return f"{s:.2f}"


def measurement_points(allowed: Sequence[float] = ALLOWED_S) -> list[tuple[str, str]]:
    """Every (item, point) of section 10's table "Where each gate and R1 is measured (Branch R)", in its order."""
    grid = [f"grid s={_s(s)}" for s in allowed]
    sk = [f"S({_s(s)})" for s in allowed]
    points: list[tuple[str, str]] = []
    points += [("G1", p) for p in ["S", *grid, *sk]]
    points += [("G2", f"{p} at 2x") for p in ["S", *grid, *sk]]
    points += [("G3", "S (all rows)"), ("G3", "S (active rows)")]
    points += [("G4", "search studies (all rows)"), ("G4", "search studies (active rows)")]
    steps = [f"{name} x{factor:g}" for name in PARAM_NAMES for factor in PLATEAU_FACTORS]
    points += [("G5", f"(a) {step}") for step in steps]
    points += [("G5", f"(b) default {step}") for step in steps]
    points += [("G5", f"(c) {p}") for p in grid]
    points += [("G6", p) for p in ["S", *grid, *sk]]
    for p in ["S", "default", *grid]:
        points += [
            ("G7", p),
            ("G7", f"{p} without the best bar-year"),
            ("G7", f"{p} without the two best bar-years"),
        ]
    points += [("G8-excess", p) for p in ["S", "default", *grid]]
    points += [("R1", p) for p in ["S", "theta_final(A)", "default", *grid]]
    for p in sk:
        points += [("S(s_k) check", f"E1 at {p}"), ("S(s_k) check", f"E2 at {p}")]
    return points


def headline(verdict_result: Mapping, results: Mapping, allowed: Sequence[float] = ALLOWED_S) -> dict:
    """The headline (section 12): the verdict's label unless EDGE; with EDGE, CANDIDATE FOR AUDIT only if every
    point of :func:`measurement_points` is True in ``results`` (keyed by (item, point)), else EDGE, NOT A CANDIDATE
    with every failing or MISSING point named. Keys that are not measurement points never move it."""
    if verdict_result["verdict"] != EDGE:
        return {"headline": verdict_result["label"], "failing": []}
    failing = [
        f"{item} at {point}" for item, point in measurement_points(allowed) if not _ok(results, (item, point))
    ]
    return {"headline": EDGE_NOT_CANDIDATE if failing else CANDIDATE, "failing": failing}


def sl_power(fill_closes) -> dict:
    """SL-P: at least 3 stop orders filled in kept rows, in at least 2 different bar-years."""
    years = set(bar_years(pd.DatetimeIndex(fill_closes)).tolist())
    n = len(fill_closes)
    return {"stops": n, "years": len(years), "holds": bool(n >= MIN_STOPS and len(years) >= MIN_STOP_YEARS)}


def sl_b(
    *,
    sharpe_phi: float,
    sharpe_s: float,
    sharpe_phi_2x: float,
    sharpe_s_2x: float,
    dd_phi: float,
    dd_s: float,
    p5_phi: float,
    p5_s: float,
    removals: Sequence[Mapping],
) -> dict:
    """SL-B (section 11A): (i) Sharpe(S^phi) >= Sharpe(S); (ii) the same at 2x; (iii) S^phi's historical max drawdown
    strictly shallower than S's; (iv) its G6 statistic strictly shallower; (v) (i) and (iii) also with BTC's best
    bar-year and two best removed (``removals``: one mapping per removal with ``sharpe_phi``, ``sharpe_s``,
    ``dd_phi`` and ``dd_s``; there must be at least one)."""
    if not removals:
        raise ValueError("sl_b: (v) needs the boom-year removals")
    parts = {
        "i": bool(sharpe_phi >= sharpe_s),
        "ii": bool(sharpe_phi_2x >= sharpe_s_2x),
        "iii": bool(dd_phi > dd_s),
        "iv": bool(p5_phi > p5_s),
        "v": all(r["sharpe_phi"] >= r["sharpe_s"] and r["dd_phi"] > r["dd_s"] for r in removals),
    }
    return {**parts, "holds": all(parts.values())}


def triggered(phi_kept, s_kept) -> bool:
    """A level triggered unless S^phi's kept returns equal S's bit for bit at 1x (verdict step 1)."""
    a, b = np.asarray(phi_kept, dtype=float), np.asarray(s_kept, dtype=float)
    if a.shape != b.shape:
        raise ValueError("triggered: S^phi and S must be scored on the same kept rows")
    return not np.array_equal(a, b)


def boom_holds(removals: Sequence[Mapping], items: Sequence[str]) -> bool:
    """E7 (``items`` = :data:`E7_ITEMS`) and SL-E7 (:data:`SL_E7_ITEMS`): every item holds (True) in every removal
    (without BTC's best bar-year, and without its two best). A MISSING item fails."""
    if not removals:
        raise ValueError("boom_holds: needs the boom-year removals")
    return all(_ok(r, k) for r in removals for k in items)


def sl_e5_holds(a: Mapping, b: Mapping) -> dict:
    """SL-E5: seed B's S^phi gives the same triggered-or-not and the same pass or fail (True, or not True) for each
    of SL-E1, SL-E2, SL-B, SL-E3 and SL-T as seed A's."""
    differ = [k for k in SL_E5_ITEMS if (a.get(k) is True) != (b.get(k) is True)]
    return {"differ": differ, "holds": not differ}


def stop_verdict(triggered: bool, criteria: Mapping, n_stops: int) -> dict:
    """One level's verdict (section 11A), in order: NOT TRIGGERED; NO EDGE (SL-E1 or SL-E2 fails); STOP DOES NOT HELP
    (SL-B, SL-E3 or SL-T fails); INCONCLUSIVE (any of SL-E4 .. SL-E8 or SL-P fails); STOP HELPS. When triggered and
    SL-P fails the label reads "(LOW POWER: k stops)"."""
    if not triggered:
        return {"verdict": NOT_TRIGGERED, "label": NOT_TRIGGERED}
    if not (_ok(criteria, "SL-E1") and _ok(criteria, "SL-E2")):
        base = NO_EDGE
    elif not all(_ok(criteria, k) for k in ("SL-B", "SL-E3", "SL-T")):
        base = STOP_DOES_NOT_HELP
    elif not all(_ok(criteria, k) for k in SL_ITEMS):
        base = INCONCLUSIVE
    else:
        base = STOP_HELPS
    label = base if _ok(criteria, "SL-P") else f"{base} (LOW POWER: {n_stops} stops)"
    return {"verdict": base, "label": label}


def overall_stop_outcome(levels: Sequence[str]) -> str:
    """NOT TRIGGERED if every level is; otherwise the least favourable verdict among the levels that triggered
    (NO EDGE < STOP DOES NOT HELP < INCONCLUSIVE < STOP HELPS). No level is chosen."""
    if not levels or any(v not in STOP_RUN_ORDER for v in levels):
        raise ValueError(f"overall_stop_outcome: verdicts must be from {STOP_RUN_ORDER}, got {levels!r}")
    triggered = [v for v in levels if v != NOT_TRIGGERED]
    if not triggered:
        return NOT_TRIGGERED
    return min(triggered, key=STOP_OUTCOME_ORDER.index)


def stop_level_line(label: str, overall: str) -> str:
    """How every level's verdict is printed (M20)."""
    return f"{label} (not a finding on its own; overall: {overall})"


def _rank(value: str, order: Sequence[str]) -> int:
    hits = [i for i, base in enumerate(order) if value == base or value.startswith(base + " (")]
    if not hits:
        raise ValueError(f"unknown outcome {value!r}; expected one of {order}")
    return max(hits)


def reported_verdict(previous: Mapping, amendment: Mapping, trigger: str) -> dict:
    """Stop rule 18. Each run: ``verdict``, ``headline``, ``stop_overall``, ``e1_rank_p``, ``e2_p``. Triggers (a),
    (b) and (c) supersede (the amendment run is reported); "other, after the verdict" reports the less favourable
    verdict, headline and stop outcome of the two (ties to the amendment run's). Any other trigger, None included,
    is refused. Both runs' E1 rank p and E2 p are listed."""
    if trigger not in TRIGGERS:
        raise ValueError(f"an amendment run must record its trigger, one of {TRIGGERS}; got {trigger!r}")
    runs = [{"e1_rank_p": r["e1_rank_p"], "e2_p": r["e2_p"]} for r in (previous, amendment)]
    if trigger != TRIGGERS[-1]:
        keys = ("verdict", "headline", "stop_overall")
        return {**{k: amendment[k] for k in keys}, "superseded": True, "runs": runs}

    def worse(key: str, order: Sequence[str]) -> str:
        a, b = previous[key], amendment[key]
        return a if _rank(a, order) < _rank(b, order) else b

    return {
        "verdict": worse("verdict", VERDICT_ORDER),
        "headline": worse("headline", HEADLINE_ORDER),
        "stop_overall": worse("stop_overall", STOP_RUN_ORDER),
        "superseded": False,
        "runs": runs,
    }


# ------------------------------------------------------------------------------------------------ the range


def default_share(theta_s: float, allowed: Sequence[float] = ALLOWED_S) -> float:
    """The allowed value nearest theta_final(A)'s s (M19): distances |s - s_k| in floating point; when the two
    smallest differ by at most 1e-12 it is a tie, which goes to the lower value."""
    s = _real(theta_s, "theta_s", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    if len(allowed) < 2:
        raise ValueError("default_share: needs at least two allowed values")
    d = sorted((abs(s - v), v) for v in allowed)
    (d0, v0), (d1, v1) = d[0], d[1]
    return min(v0, v1) if d1 - d0 <= TIE_TOL else v0


def riskiest_step(p5: Mapping[float, float]) -> float:
    """The allowed value with the most negative G6 statistic; ties go to the higher s (M19)."""
    if not p5 or not all(math.isfinite(v) for v in p5.values()):
        raise ValueError(f"riskiest_step: needs a finite G6 statistic per value, got {dict(p5)!r}")
    return max(p5, key=lambda s: (-p5[s], s))


def narrowing(
    values: Mapping[float, Mapping], default: float, budget: float, *, g6_fails_at_s: bool = False
) -> dict:
    """What section 8's narrowing would do (reported next to the headline, never applied here). ``values``: per
    allowed s, ``p5`` (the deepest of its grid step's and S(s_k)'s G6 statistic), ``risk_fail`` (G6 fails there) and
    ``other_fail`` (any non-risk failure there). Statuses: ``not needed``; ``fails`` (G6 fails at S, a non-risk
    failure, or a drop would take the default); ``not possible`` (the deepest p5 is not at an end); ``keeps``
    (values dropped one at a time from the riskiest end until no risk failure is left, each new edge's margin
    p5 + budget logged)."""
    order = sorted(values)
    if default not in values:
        raise ValueError("narrowing: the default must be one of the values")
    base = {"kept": order, "dropped": [], "margins": []}
    if g6_fails_at_s:
        return {**base, "status": "fails", "line": "narrowing fails: G6 fails at S, the walk-forward choice"}
    if any(values[s]["other_fail"] for s in order):
        return {
            **base,
            "status": "fails",
            "line": "narrowing fails: a failure that is not a risk-limit failure",
        }
    if not any(values[s]["risk_fail"] for s in order):
        return {**base, "status": "not needed", "line": "no narrowing needed"}
    end = riskiest_step({s: values[s]["p5"] for s in order})
    if end not in (order[0], order[-1]):
        line = f"narrowing not possible: the deepest p5 is at s = {_s(end)}, not an end"
        return {**base, "status": "not possible", "line": line}
    kept = list(order) if end == order[-1] else list(reversed(order))
    dropped, margins = [], []
    while any(values[s]["risk_fail"] for s in kept):
        if kept[-1] == default:
            line = "narrowing fails: it would drop the default"
            return {
                "kept": sorted(kept),
                "dropped": dropped,
                "margins": margins,
                "status": "fails",
                "line": line,
            }
        dropped.append(kept.pop())
        margins.append((kept[-1], values[kept[-1]]["p5"] + budget))
    kept = sorted(kept)
    shown = ", ".join(_s(s) for s in kept)
    line = f"narrowing would keep {{{shown}}}, with margin {margins[-1][1]:.4f}"
    return {"kept": kept, "dropped": dropped, "margins": margins, "status": "keeps", "line": line}


# ------------------------------------------------------------------------------------------------ projection


def project_cpu_minutes(timings: Mapping[str, float], counts: Mapping[str, int]) -> float:
    """Stop rule 17's projection: the sum over :data:`TIMING_KEYS` of seconds per unit x units, in minutes."""
    if set(timings) != set(TIMING_KEYS) or set(counts) != set(TIMING_KEYS):
        raise ValueError(f"project_cpu_minutes: timings and counts must have exactly the keys {TIMING_KEYS}")
    total = 0.0
    for key in TIMING_KEYS:
        total += _real(timings[key], f"timing {key}", 0.0, low_inclusive=True) * _count(counts[key], key, 0)
    return total / 60.0


def projection_allows(minutes: float, budget: float) -> bool:
    """A projection of exactly the budget starts; above it refuses (stop rule 17)."""
    return bool(minutes <= budget)


# ------------------------------------------------------------------------------------------------ synthetic panels


def _panel_from_log_returns(
    index: pd.DatetimeIndex, log_ret: np.ndarray, start=(10_000.0, 500.0)
) -> pd.DataFrame:
    frames = {}
    for a, asset in enumerate(ASSETS):
        close = start[a] * np.exp(np.cumsum(log_ret[:, a]))
        open_ = np.concatenate([[close[0]], close[:-1]])
        frames[asset] = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close),
                "low": np.minimum(open_, close),
                "close": close,
                "volume": np.ones(len(close)),
            },
            index=index,
        )
    return make_panel(frames, snapshot_id="synthetic")


def random_walk_panel(seed: int, index=None) -> pd.DataFrame:
    """The slow calibration test's panel (section 9): on the train grid, daily log returns 0.001 + sd * e with sd
    0.04 (BTC) and 0.05 (ETH), e_BTC = g_0 and e_ETH = 0.8 g_0 + 0.6 g_1 from ``default_rng(seed).standard_normal((n,
    2))``; closes from 10,000 and 500 times exp of the cumulative sum; open = previous close (the first open = the
    first close); high = max(open, close), low = min(open, close); volume 1."""
    idx = train_grid() if index is None else pd.DatetimeIndex(index)
    g = np.random.default_rng(_count(seed, "seed", 0)).standard_normal((len(idx), 2))
    e = np.column_stack([g[:, 0], 0.8 * g[:, 0] + 0.6 * g[:, 1]])
    return _panel_from_log_returns(idx, 0.001 + np.array([0.04, 0.05]) * e)


GARCH_ALPHA, GARCH_BETA, T_DF = 0.08, 0.90, 5


def garch_panel(j: int, index=None) -> pd.DataFrame:
    """A0's volatility-clustering panel j (section 9, M21): ``rng = default_rng(10_000 + j)``; x =
    ``rng.standard_t(5, size=(n, 2)) / sqrt(5 / 3)``; ETH's innovation 0.8 x_BTC + 0.6 x_ETH; each a unit-variance
    GARCH(1,1) (alpha 0.08, beta 0.90, omega = 1 - alpha - beta; previous variance 1 and previous shock 0, as
    ``lab.data.synthetic``); daily log returns 0.001 + (0.04, 0.05) g; bars as :func:`random_walk_panel`."""
    idx = train_grid() if index is None else pd.DatetimeIndex(index)
    rng = np.random.default_rng(10_000 + _count(j, "j", 0))
    x = rng.standard_t(T_DF, size=(len(idx), 2)) / math.sqrt(T_DF / (T_DF - 2))
    innov = np.column_stack([x[:, 0], 0.8 * x[:, 0] + 0.6 * x[:, 1]])
    omega = 1.0 - GARCH_ALPHA - GARCH_BETA
    g = np.empty_like(innov)
    for a in range(2):
        var, prev = 1.0, 0.0
        for t in range(len(idx)):
            var = omega + GARCH_ALPHA * prev**2 + GARCH_BETA * var
            prev = math.sqrt(var) * innov[t, a]
            g[t, a] = prev
    return _panel_from_log_returns(idx, 0.001 + np.array([0.04, 0.05]) * g)
