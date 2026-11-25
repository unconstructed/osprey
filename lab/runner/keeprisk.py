"""keep-risk-steady: the "keep my risk steady" tool, its yardsticks, its measures, its luck control and its rules.

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the reference
rebalancer, not NautilusTrader (AGENTS.md hard rule 3). ``research/keep-risk-steady/PLAN.md`` is the contract; section
numbers below are that file's. No existing file is changed: the swing is ``volsteady.sigma_hat`` / ``scale`` /
``quarter``, the check closes ``trend.check_closes``, the targets ``trend.in_force``, the copies ``trend.Schedule`` /
``shifted`` / ``span_targets`` / ``guarded_offsets`` / ``rank_holds``, the executor a new driver of
``portfolio._simulate``, the falls and fees ``holdmix.money_metrics``, the index ``protect.index_signal`` and the
resampling ``montecarlo.stationary_bootstrap_indices``.

The rule (section 5)
--------------------
- **The mix's daily return** at close t >= 1 (:func:`basket_returns`): x_t = ``math.log1p(f * (C_BTC,t / C_BTC,t-1 -
  1.0) + (1.0 - f) * (C_ETH,t / C_ETH,t-1 - 1.0))``; x_0 is NaN. At f = 0.50 it is ``volsteady.basket_returns``.
- **The swing** sigma(c) = ``volsteady.sigma_hat(x, 14, rows=[c])[c]`` (from row 14 on) and **the level** tau = w x
  ``math.sqrt(365.0 / 7.0)`` (:func:`level`); **the step** q = ``volsteady.quarter(volsteady.scale(sigma, tau))``.
- **Decisions** (:func:`q_path`): the switch-on decision at the run's first close r0 (q(r0) when r0 >= 14, else 1),
  then every Monday 00:00 UTC close c >= 14 with c > r0 (``trend.check_closes``). The q in force at close t is the
  latest decision's. The signal reads the whole source panel: a window run's r0 is a panel row.
- **The targets** at close t: ``trend.in_force(ones, s * q(t), f=f)``, i.e. (s q f, s q (1 - f)) (:func:`rule_targets`).
- **The executor** (:func:`ride_run`, one order per close, decided at close t and filled at the open of t + 1, the last
  close's decision never filled): close 0 orders the targets in force (``first``; an all-USDC target sends no order);
  at a Monday close t >= 1 it orders the targets in force when they differ from the last order's (``step``), else when
  some coin with target T > 0 has |w - T| > 0.25 T at close t (``drift``, strict); at any close t >= 1 without such an
  order, a breach of the Steady limits (``portfolio._breach_test`` at the limits, ``LIMIT_TOL``) orders them
  (``limit``). Every distinct target vector passes ``check_targets`` with the limits as read and h = 0.02 first.
- **Live** (:class:`KeepRiskStream`): fed one close at a time, with :meth:`KeepRiskStream.switch_on` at the switch-on
  close, it gives :func:`q_path`'s q in force bit for bit.

The yardsticks (section 6), the measures (section 8), the luck control (section 9) and the rules (section 10)
-----------------------------------------------------------------------------------------------------------
N holds the user's share s, X the rule's average in-force share x (:func:`matched_share`), X_eq x exp(V)
(:func:`equal_calm_share`), each through :func:`ride_run` with a constant target. :func:`run_measures`,
:func:`rule_measures` and :func:`compare` give section 8's numbers; :func:`index_set`, :func:`risk_x`, :func:`holm`,
:func:`e1` and :func:`ride_label` section 9's; :func:`d1`, :func:`d2` and :func:`d3` section 10's. A MISSING number is
None (or NaN in a table); a rule that needs one gives :data:`MISSING`, never a pass. The readings pinned where the plan
is loosely worded are :data:`READINGS_PINNED`.

pandas caveat (as in portfolio.py): ``attrs`` holds arrays and frames; drop them (``piece.attrs = {}``) before
``pd.concat`` or ``to_parquet``.
"""

from __future__ import annotations

import hashlib
import math
import numbers
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import NamedTuple

import numpy as np
import pandas as pd

from lab.runner import holdmix, protect, trend, volsteady
from lab.runner.holdmix import ConsistencyError
from lab.runner.portfolio import ASSETS, _breach_test, _simulate, check_targets, validate_panel
from lab.runner.reference import Costs, _check_params, _param_float, _param_int, _real
from lab.validation.montecarlo import stationary_bootstrap_indices

__all__ = [
    "MIXES",
    "W_VALUES",
    "ConsistencyError",
    "KeepRiskStream",
    "QPath",
    "basket_returns",
    "check_order_targets",
    "check_yardstick",
    "compare",
    "copy_schedule",
    "copy_share",
    "d1",
    "d2",
    "d3",
    "down_day",
    "e1",
    "equal_calm_share",
    "exact_mean",
    "holm",
    "index_set",
    "keep_risk",
    "level",
    "matched_share",
    "q_hash",
    "q_path",
    "resampled_means",
    "ride_label",
    "ride_run",
    "ride_v",
    "risk_x",
    "rule_measures",
    "rule_targets",
    "run_measures",
    "shifted_copy",
    "step_hash",
    "swing",
]

# ------------------------------------------------------------------------------------------------ pinned values

LOOKBACK = 14  # the fixed look-back (section 4)
DESCRIBE_LOOKBACKS = (7, 28)  # descriptions only (section 7)
W_VALUES = (0.08, 0.10, 0.12, 0.15)  # the setting (section 4)
S_VALUES = (0.30, 0.40, 0.50, 0.60)
F_VALUES = (0.50, 0.75)
MIXES = tuple((s, f) for s in S_VALUES for f in F_VALUES)  # 8 mixes
WEEKDAY = 0  # Monday 00:00 UTC
BAND = 0.25  # the relative trading band (section 4)
HEADROOM = 0.02
DEPOSIT = 5000.0
SMALL_DEPOSIT = 500.0  # the small-wallet description
STEADY_MIN_CASH = 0.20  # the run refuses other values as read (section 4)
STEADY_MAX_COIN = 0.60
YEAR_DAYS = 365
WEEK_TO_YEAR = math.sqrt(365.0 / 7.0)  # tau = w x sqrt(365 / 7) (section 5.3)
MEAN_BLOCK = 60  # the resampling (section 9.2)
RESAMPLES = 10_000
RESAMPLE_SEED = 0
ALPHA = 0.05
DELTA = 0.10  # the equivalence margin: a cut of 10% (section 9.2)
EQ_BOUND = math.log(1.0 - DELTA)  # ln 0.9
COST_MARGIN = 0.02  # m = 2 points a year, as a fraction (the cost flag, section 9.5)
COST_MARGIN_POINTS = 2.0  # m in points (D1 rule 3, inclusive)
LEAD_GUARD = trend.LEAD_GUARD  # 52 weeks
REBOUND_DAYS = 90
LAMBDA_TOL = 1e-12
INTERVAL = (5.0, 95.0)  # V's 90% interval
DESCRIBE_PERCENTILES = (10.0, 50.0, 90.0)
FALL_PERCENTILE = 90.0  # Q
BOOM_MIN_WINDOWS = protect.BOOM_MIN_WINDOWS  # 12
DAY_US = holdmix.DAY_US
KINDS = ("rule", "N", "X", "X_eq")
COPY_KINDS = ("copy", "copy_X")
REASONS = ("first", "step", "drift", "limit")
YARDSTICK_REASONS = ("first", "drift", "limit")
ZERO = (0.0, 0.0)

MISSING = "MISSING"
NOT_STEPPING = "DOES NOT STEP BACK"
ROUGHER = "ROUGHER THAN HOLDING LESS"
CALMER = "CALMER THAN HOLDING LESS"
BELOW_NOTICE = "SMALLER, BUT BELOW NOTICE"
NO_DIFFERENCE = "NO NOTICEABLE DIFFERENCE"
CANT_TELL = "CAN'T TELL"
LABELS = (MISSING, NOT_STEPPING, ROUGHER, CALMER, BELOW_NOTICE, NO_DIFFERENCE, CANT_TELL)
D1_LABELS = (CALMER, CANT_TELL)  # D1 rule 2
COST_FLAG = "COSTS MORE THAN HOLDING LESS"
NO_DEFAULT = "NO DEFAULT"
ROBUST = "ROBUST"
NOT_ROBUST = "NOT ROBUST"
OK = "ok"
LABEL = "SCOUTING, placeholder costs, train years 2017-2022, reference engine; claims no return edge"

READINGS_PINNED = {
    "matched_share": "x is the correctly rounded mean of the in-force share over rows 0 .. n-2 (the exact sum, one "
    "rounding: fractions.Fraction). It equals section 6's math.fsum(share[0 .. n-2]) / (n - 1) except in the last bit "
    "where that formula rounds twice; with a constant share it is that share exactly, as section 12's identity 'a "
    "setting that never steps gives rule = X = N' and section 9.4's 'X is N and V = 0' need (fsum / (n - 1) gives "
    "0.4 + 1 ulp for s = 0.40 on a 729-row window)",
    "mondays": "The executor's Monday closes are every Monday 00:00 UTC close t >= 1 of the run (rows before panel row "
    "14 included: the band applies there, with q_on in force); the q decisions are the Monday closes c >= 14 of the "
    "panel after the switch-on close (section 5.5)",
    "switch_on_monday": "A run whose first close is a Monday at panel row >= 14 makes one decision there, the switch-on "
    "(the same q as that Monday's check)",
    "last_order": "The last order's targets start as all USDC (0, 0), so an all-USDC switch-on sends no order and the "
    "first Monday with q > 0 is a step",
    "steps": "q steps are counted at the Monday checks of the run: a step-down where the new q is below the q in "
    "force before it, a step-up where above; the switch-on decision is not a step",
    "longest": "The longest stretch with q < 1, in days: a maximal run of closes a .. b with q < 1, from close a to "
    "the close after b (the last close when b is the last)",
    "over_cap": "A week runs from one Monday close of the run to the next (6 returns across Kraken's missing "
    "2018-01-13); its move is sqrt(math.fsum(r^2)) over those returns, over the cap when > s x w (strict); weeks "
    "not wholly inside the run are not counted",
    "realised": "A run's realised average crypto weight is the mean of position (w_BTC + w_ETH at the close) over "
    "rows 1 .. n-1",
    "rebound": "t_low is the first close of the run with the lowest I; the gap is 100 x (prod(1 + r_N) - prod(1 + "
    "r_rule)) over rows t_low + 1 .. t_end, t_end the first close at least 90 days after t_low, else the last close "
    "(0 when t_low is the last close)",
    "trades": "Orders after the first buy a year = (orders - first) x 365 / span; the busiest 30 days count the "
    "fills (close after the order) of orders after the first buy in (t - 30 days, t] (trend.rolling_count)",
    "holm_missing": "A MISSING p_calm in a (pool, mix) family makes every setting's Holm outcome in that family "
    "MISSING; a setting that never steps back enters with p_calm = 1 (section 9.2)",
    "label_missing": "Holm and E1 are needed only for V < 0: if either is False the cell is not CALMER or SMALLER; "
    "if neither is False and one is MISSING the label is MISSING",
    "d1_missing": "D1's rules are three-valued (True, False, MISSING): a setting is unusable when any rule fails at "
    "any mix, MISSING when none fails and one is MISSING; D1's default is MISSING when any setting is MISSING or a "
    "run of the pool failed (an X_eq excepted). The first failure is recorded in mix order, rules 1-3",
    "kept_rows": "A check without some bar-years drops the return rows whose bar-year (trend.bar_years) is removed: "
    "DD, V, every V_u and the resampling (a new index set over the kept rows, seed 0) on the kept rows only",
    "x_eq": "X_eq's share is lambda x x_eq with x_eq = x exp(V) and lambda the largest in [0, 1] (bisection to 1e-12) "
    "whose targets (share f, share (1 - f)) pass check_targets with h; lambda = 1 when they pass",
}


def _count(value, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def _frac(value, name: str) -> float:
    return _real(value, name, 0.0, low_inclusive=True, high=1.0, high_inclusive=True)


def _limits(limits: Mapping) -> tuple[float, float]:
    if not isinstance(limits, Mapping) or limits.get("min_cash") is None or limits.get("max_coin") is None:
        raise ValueError("limits must hold min_cash and max_coin (portfolio.risk_limits('steady'))")
    return float(limits["min_cash"]), float(limits["max_coin"])


def _finite(x) -> bool:
    return x is not None and isinstance(x, numbers.Real) and math.isfinite(float(x))


# ------------------------------------------------------------------------------------------------ the signal


def basket_returns(bars: pd.DataFrame, f) -> np.ndarray:
    """x_t = log1p(f (C_BTC,t / C_BTC,t-1 - 1) + (1 - f)(C_ETH,t / C_ETH,t-1 - 1)) for t >= 1; NaN at row 0."""
    validate_panel(bars)
    f = _frac(f, "f")
    cb = bars[(ASSETS[0], "close")].to_numpy(dtype=float).tolist()
    ce = bars[(ASSETS[1], "close")].to_numpy(dtype=float).tolist()
    out = [math.nan]
    for t in range(1, len(cb)):
        out.append(math.log1p(f * (cb[t] / cb[t - 1] - 1.0) + (1.0 - f) * (ce[t] / ce[t - 1] - 1.0)))
    return np.asarray(out, dtype=float)


def swing(bars: pd.DataFrame, f, lookback=LOOKBACK) -> np.ndarray:
    """sigma at every close (``volsteady.sigma_hat`` of :func:`basket_returns`); NaN before row ``lookback``."""
    return volsteady.sigma_hat(basket_returns(bars, f), _count(lookback, "lookback", 2))


def level(w) -> float:
    """tau = w x sqrt(365 / 7), the annual figure of a weekly move w (section 5.3)."""
    return _real(w, "w", 0.0, low_inclusive=False) * WEEK_TO_YEAR


def _q(sigma: float, tau: float) -> float:
    return volsteady.quarter(volsteady.scale(sigma, tau))


class QPath(NamedTuple):
    """The point-in-time steps of one run (section 5.5), in run rows (0 = the switch-on close)."""

    q: np.ndarray  # (n,) the q in force at each close of the run
    checks: np.ndarray  # int64 run rows of the Monday checks after the switch-on close
    q_checks: np.ndarray  # q decided at each check
    sigma_checks: np.ndarray  # sigma at each check
    q_on: float  # the switch-on decision
    sigma_on: float  # sigma at the switch-on close (NaN with fewer than ``lookback`` returns)
    start: int  # the panel row of the run's first close


def q_path(
    panel: pd.DataFrame,
    w,
    f,
    *,
    start: int = 0,
    stop: int | None = None,
    lookback=LOOKBACK,
    weekday=WEEKDAY,
    sigma=None,
) -> QPath:
    """The q path of a run on panel rows ``start .. stop - 1`` (the whole panel by default), the signal read from the
    whole panel (module docstring). ``sigma`` is :func:`swing`'s output for this panel, f and lookback (computed when
    None)."""
    validate_panel(panel)
    n_rows = _count(lookback, "lookback", 2)
    n = len(panel)
    stop = n if stop is None else _count(stop, "stop", 2)
    start = _count(start, "start")
    if not start < stop - 1 or stop > n:
        raise ValueError(
            f"q_path: rows {start} .. {stop - 1} are not a run of at least 2 closes of the panel"
        )
    sig = swing(panel, f, n_rows) if sigma is None else np.asarray(sigma, dtype=float)
    if sig.shape != (n,):
        raise ValueError("q_path: sigma must hold one value per close of the panel")
    tau = level(w)
    sigma_on = float(sig[start]) if start >= n_rows else math.nan
    q_on = _q(sigma_on, tau) if start >= n_rows else 1.0
    rows = trend.check_closes(panel.index, weekday, n_rows)
    rows = rows[(rows > start) & (rows < stop)]
    q = np.full(stop - start, q_on)
    q_checks = np.empty(len(rows))
    for i, c in enumerate(rows.tolist()):
        q_checks[i] = _q(float(sig[c]), tau)
        q[c - start :] = q_checks[i]
    return QPath(q, rows - start, q_checks, sig[rows].copy(), q_on, sigma_on, start)


def q_hash(qp: QPath) -> str:
    """SHA-256 of a q path: the q in force (float64) and the check rows (int64), little-endian."""
    digest = hashlib.sha256()
    digest.update(np.asarray(qp.q, dtype="<f8").tobytes())
    digest.update(np.asarray(qp.checks, dtype="<i8").tobytes())
    return digest.hexdigest()


class KeepRiskStream:
    """The live tool: fed one close at a time (from the panel's first close), it gives :func:`q_path`'s q in force
    bit for bit. Call :meth:`switch_on` after the switch-on close; :meth:`update` returns None before it."""

    def __init__(self, w, f, *, lookback=LOOKBACK, weekday=WEEKDAY):
        self.tau = level(w)
        self.f = _frac(f, "f")
        self.lookback = _count(lookback, "lookback", 2)
        self.weekday = trend._weekday(weekday)
        self._x: deque[float] = deque(maxlen=self.lookback)
        self._row = -1
        self._last: pd.Timestamp | None = None
        self._prev: tuple[float, float] | None = None
        self._on = False
        self.q: float | None = None
        self.sigma = math.nan

    def _sigma(self) -> float:
        window = [math.nan, *self._x]
        return float(
            volsteady.sigma_hat(np.asarray(window), self.lookback, rows=[self.lookback])[self.lookback]
        )

    def update(self, ts, close_btc, close_eth) -> float | None:
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            raise ValueError(f"closes must be tz-aware (UTC close times), got {ts!r}")
        stamp = stamp.tz_convert("UTC")
        if self._last is not None and stamp <= self._last:
            raise ValueError(f"closes must be strictly increasing, got {ts!r} after {self._last!r}")
        cb, ce = (_real(float(p), "close", 0.0, low_inclusive=False) for p in (close_btc, close_eth))
        self._last = stamp
        self._row += 1
        if self._prev is not None:
            pb, pe = self._prev
            self._x.append(math.log1p(self.f * (cb / pb - 1.0) + (1.0 - self.f) * (ce / pe - 1.0)))
        self._prev = (cb, ce)
        if self._on and self._row >= self.lookback and stamp.day_of_week == self.weekday:
            self.sigma = self._sigma()
            self.q = _q(self.sigma, self.tau)
        return self.q

    def switch_on(self) -> float:
        """The switch-on decision at the latest close fed (section 5.5)."""
        if self._row < 0 or self._on:
            raise ValueError("switch_on: feed the switch-on close first, and switch on once")
        self._on = True
        if self._row >= self.lookback:
            self.sigma = self._sigma()
            self.q = _q(self.sigma, self.tau)
        else:
            self.q = 1.0
        return self.q


# ------------------------------------------------------------------------------------------------ the executor


def rule_targets(q, s, f) -> np.ndarray:
    """(s q f, s q (1 - f)) per close: ``trend.in_force(ones, s * q, f=f)``."""
    q = np.asarray(q, dtype=float)
    share = _frac(s, "s") * q
    return trend.in_force(np.ones((len(q), len(ASSETS)), dtype=np.int8), share, f=f)


def constant_targets(share, n: int, f) -> np.ndarray:
    """A yardstick's targets: one crypto share on every close."""
    n = _count(n, "n", 1)
    return trend.in_force(np.ones((n, len(ASSETS)), dtype=np.int8), np.full(n, _frac(share, "share")), f=f)


def _target_array(targets, n: int) -> np.ndarray:
    a = np.array(targets, dtype=float)
    if a.shape != (n, len(ASSETS)) or not np.isfinite(a).all() or (a < 0).any() or (a.sum(axis=1) > 1).any():
        raise ValueError(f"targets must be a finite ({n}, 2) array of target vectors with w_BTC + w_ETH <= 1")
    return a


def ride_run(
    bars: pd.DataFrame, targets, *, limits: Mapping, costs: Costs, band=BAND, weekday=WEEKDAY
) -> pd.DataFrame:
    """The executor (section 5.7; module docstring). ``targets``: the in-force (w_BTC, w_ETH) at each close.
    ``band=math.inf`` never drifts. Adds ``targets``, ``reasons``, ``order_targets`` and ``order_hash``."""
    validate_panel(bars)
    if not isinstance(costs, Costs):
        raise ValueError(f"ride_run: costs must be a Costs instance built at run start, got {costs!r}")
    min_cash, max_coin = _limits(limits)
    if isinstance(band, bool) or not isinstance(band, numbers.Real) or not (band >= 0.0):
        raise ValueError(f"band must be a number >= 0 (math.inf: never drifts), got {band!r}")
    band = float(band)
    day = trend._weekday(weekday)
    n = len(bars)
    tg = _target_array(targets, n)
    for w_btc, w_eth in np.unique(tg, axis=0).tolist():
        try:
            check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM)
        except ValueError as exc:
            raise ValueError(f"ride_run: a target vector breaks the Steady limits as read: {exc}") from exc
    rows = [tuple(r) for r in tg.tolist()]
    monday = (bars.index.day_of_week.to_numpy() == day).tolist()
    breached = _breach_test(min_cash, max_coin)
    labels: dict[int, str] = {}
    last = [ZERO]

    def decide(t: int, w: tuple[float, ...]) -> tuple[float, ...] | None:
        vector = rows[t]
        reason = None
        if t == 0:
            reason = "first" if vector != ZERO else None
        else:
            if monday[t]:
                if vector != last[0]:
                    reason = "step"
                elif any(vector[a] > 0.0 and abs(w[a] - vector[a]) > band * vector[a] for a in range(2)):
                    reason = "drift"
            if reason is None and breached(w):
                reason = "limit"
        if reason is None:
            return None
        labels[t] = reason
        last[0] = vector
        return vector

    result = _simulate(bars, costs, decide)
    orders = result.attrs["orders"]
    result.attrs["targets"] = tg
    result.attrs["reasons"] = np.asarray([labels[t] for t in orders.tolist()], dtype=object)
    result.attrs["order_targets"] = tg[orders]
    result.attrs["order_hash"] = trend.order_hash(result)
    return result


def run_rule(bars: pd.DataFrame, qp: QPath, s, f, *, limits: Mapping, costs: Costs) -> pd.DataFrame:
    """The rule on a run's bars (rows ``qp.start ..`` of the panel) with its q path; adds ``q`` and ``share``."""
    if len(qp.q) != len(bars):
        raise ValueError("run_rule: the q path must cover the run's closes")
    result = ride_run(bars, rule_targets(qp.q, s, f), limits=limits, costs=costs)
    result.attrs["q"] = qp.q
    result.attrs["share"] = _frac(s, "s") * np.asarray(qp.q, dtype=float)
    return result


def run_yardstick(bars: pd.DataFrame, share, f, *, limits: Mapping, costs: Costs) -> pd.DataFrame:
    """N, X or X_eq: one crypto share held by the same executor (section 6)."""
    result = ride_run(bars, constant_targets(share, len(bars), f), limits=limits, costs=costs)
    result.attrs["share"] = float(share)
    return result


_PARAMS = frozenset({"w", "s", "f", "lookback"})


def parse_params(params) -> dict:
    """Strict params: ``w`` (> 0), ``s`` and ``f`` (in [0, 1]) and ``lookback`` (an integer >= 2, default 14)."""
    p = _check_params("keep_risk", params, _PARAMS)
    return {
        "w": _param_float(p, "w", low=0.0, low_inclusive=False),
        "s": _param_float(p, "s", low=0.0, low_inclusive=True, high=1.0, high_inclusive=True),
        "f": _param_float(p, "f", low=0.0, low_inclusive=True, high=1.0, high_inclusive=True),
        "lookback": _param_int(p, "lookback", LOOKBACK, minimum=2),
    }


def keep_risk(params: Mapping, bars: pd.DataFrame, *, limits: Mapping, costs: Costs) -> pd.DataFrame:
    """The ``BacktestFn``: the tool switched on at the panel's first close. Bind ``limits`` and ``costs`` with
    ``functools.partial``. Adds the q path's ``q``, ``share``, ``checks``, ``q_checks``, ``sigma_checks`` and
    ``q_on``."""
    p = parse_params(params)
    qp = q_path(bars, p["w"], p["f"], lookback=p["lookback"])
    result = run_rule(bars, qp, p["s"], p["f"], limits=limits, costs=costs)
    result.attrs.update(checks=qp.checks, q_checks=qp.q_checks, sigma_checks=qp.sigma_checks, q_on=qp.q_on)
    return result


def check_order_targets(result: pd.DataFrame, limits: Mapping) -> None:
    """Every order's targets pass ``check_targets`` with the limits and h = 0.02 (section 11)."""
    min_cash, max_coin = _limits(limits)
    for w_btc, w_eth in np.asarray(result.attrs["order_targets"]).reshape(-1, 2).tolist():
        try:
            check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM)
        except ValueError as exc:
            raise ConsistencyError(f"an order's targets break the Steady limits: {exc}") from exc


def check_yardstick(result: pd.DataFrame, share, f) -> None:
    """A yardstick never steps: reasons ``first``, ``drift`` or ``limit`` only, and its target is ``share`` at split
    ``f`` on every close, bit for bit (section 11)."""
    reasons = set(np.asarray(result.attrs["reasons"]).tolist())
    if not reasons <= set(YARDSTICK_REASONS):
        raise ConsistencyError(f"a yardstick ordered for {sorted(reasons - set(YARDSTICK_REASONS))}")
    tg = np.asarray(result.attrs["targets"])
    if not np.array_equal(tg, constant_targets(share, len(tg), f)):
        raise ConsistencyError("a yardstick's targets are not its share on every close")


def step_hash(result: pd.DataFrame) -> str:
    """SHA-256 of the close times (int64 microseconds) of the ``step`` orders."""
    orders = np.asarray(result.attrs["orders"], dtype=np.int64)
    steps = orders[np.asarray(result.attrs["reasons"]) == "step"] if len(orders) else orders
    return hashlib.sha256(np.asarray(result.index.asi8[steps], dtype="<i8").tobytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ the yardsticks


def exact_mean(values) -> float:
    """The correctly rounded mean of ``values`` (the exact sum, one rounding; READINGS_PINNED["matched_share"])."""
    counts = Counter(np.asarray(values, dtype=float).tolist())
    n = sum(counts.values())
    if not n:
        raise ValueError("exact_mean: no values")
    total = sum((Fraction(v) * k for v, k in counts.items()), Fraction(0))
    return float(total / n)


def matched_share(share) -> float:
    """x: the in-force share averaged over the rows whose decision can fill (rows 0 .. n-2)."""
    a = np.asarray(share, dtype=float)
    if a.ndim != 1 or len(a) < 2:
        raise ValueError("matched_share: one share per close of a run of at least 2 closes")
    return exact_mean(a[:-1])


def equal_calm_share(x, v, f, limits: Mapping) -> dict:
    """X_eq (section 6): x_eq = x exp(V), scaled down by the largest lambda <= 1 (bisection to 1e-12) whose targets
    pass ``check_targets`` with h. Returns ``share`` (lambda x_eq), ``x_eq``, ``clipped`` and ``lambda``."""
    min_cash, max_coin = _limits(limits)
    f = _frac(f, "f")
    x_eq = _frac(x, "x") * math.exp(_real(v, "V", -math.inf, low_inclusive=False))

    def passes(lam: float) -> bool:
        share = lam * x_eq
        try:
            check_targets(
                share * f, share * (1.0 - f), min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM
            )
        except ValueError:
            return False
        return True

    if passes(1.0):
        return {"share": x_eq, "x_eq": x_eq, "clipped": False, "lambda": 1.0}
    low, high = 0.0, 1.0
    while high - low > LAMBDA_TOL:
        mid = (low + high) / 2.0
        if passes(mid):
            low = mid
        else:
            high = mid
    return {"share": low * x_eq, "x_eq": x_eq, "clipped": True, "lambda": low}


# ------------------------------------------------------------------------------------------------ the copies


def copy_schedule(qp: QPath, s) -> trend.Schedule:
    """The rule's steps as a ``trend.Schedule`` (section 9.3): checks c_k, z = 1, share s q_k, one fold, the head at
    s q_on."""
    s = _frac(s, "s")
    w = len(qp.checks)
    if not w:
        raise ValueError("copy_schedule: the run holds no Monday check")
    first = int(qp.checks[0])
    return trend.Schedule(
        np.asarray(qp.checks, dtype=np.int64),
        np.ones((w, len(ASSETS)), dtype=np.int8),
        s * np.asarray(qp.q_checks, dtype=float),
        np.zeros(w, dtype=np.int64),
        np.ones((first, len(ASSETS)), dtype=np.int8),
        s * qp.q_on,
    )


def copy_share(schedule: trend.Schedule, n: int) -> np.ndarray:
    """The in-force share of a schedule on an n-row run, as ``trend.span_targets`` builds it."""
    checks = schedule.checks
    first = int(checks[0])
    latest = np.searchsorted(checks, np.arange(first, n), side="right") - 1
    return np.concatenate([np.full(first, schedule.head_share), schedule.share[latest]])


def shifted_copy(schedule: trend.Schedule, u: int, n: int, f) -> tuple[np.ndarray, np.ndarray]:
    """Copy u's per-row targets and in-force share (``trend.shifted`` then ``trend.span_targets``)."""
    moved = trend.shifted(schedule, u)
    targets, _ = trend.span_targets(moved, n, f=f)
    return targets, copy_share(moved, n)


# ------------------------------------------------------------------------------------------------ the measures


def _returns(result: pd.DataFrame) -> np.ndarray:
    return result["ret"].to_numpy(dtype=float)[1:]


def down_day(returns, keep=None) -> float:
    """DD = sqrt(math.fsum(min(r, 0)^2) / count) over ``returns`` (the rows ``keep`` only)."""
    r = np.asarray(returns, dtype=float)
    if keep is not None:
        r = r[np.asarray(keep, dtype=bool)]
    if not len(r):
        raise ValueError("down_day: no returns")
    return math.sqrt(math.fsum(min(v, 0.0) ** 2 for v in r.tolist()) / len(r))


def ride_v(dd_a: float, dd_b: float) -> float | None:
    """V = ln DD(a) - ln DD(b); None (MISSING) when either is 0."""
    if not (dd_a > 0.0 and dd_b > 0.0):
        return None
    return math.log(dd_a) - math.log(dd_b)


def _span_days(index: pd.DatetimeIndex) -> float:
    return (int(index.asi8[-1]) - int(index.asi8[0])) / DAY_US


def _cagr(result: pd.DataFrame) -> float:
    growth = float(np.prod(1.0 + _returns(result)))
    return growth ** (YEAR_DAYS / _span_days(result.index)) - 1.0


def _over_cap(result: pd.DataFrame, cap: float) -> float:
    idx = result.index
    mondays = np.flatnonzero(idx.day_of_week.to_numpy() == WEEKDAY).tolist()
    r = result["ret"].to_numpy(dtype=float)
    weeks = over = 0
    for a, b in zip(mondays, mondays[1:], strict=False):
        weeks += 1
        over += int(math.sqrt(math.fsum((r[a + 1 : b + 1] ** 2).tolist())) > cap)
    return over / weeks if weeks else math.nan


def _trading(result: pd.DataFrame) -> dict:
    orders = np.asarray(result.attrs["orders"], dtype=np.int64)
    reasons = np.asarray(result.attrs["reasons"], dtype=object)
    idx = result.index
    later = orders[reasons != "first"] if len(orders) else orders
    per_year = YEAR_DAYS / _span_days(idx)
    busiest = trend.rolling_count(idx[later + 1], idx) if len(later) else np.zeros(1)
    out = {f"orders_{r}": int((reasons == r).sum()) for r in REASONS}
    out.update(orders=len(orders), orders_per_year=len(later) * per_year, busiest_30d=int(busiest.max()))
    return out


def run_measures(result: pd.DataFrame, costs: Costs, *, s, w) -> dict:
    """Section 8's per-run numbers: DD, F (the worst fall, a positive fraction), the worst week and day, the over-cap
    share at s x w, CAGR, fees and gas a year and the first buy's cost (``holdmix.money_metrics``, whose fee check
    runs), the realised average crypto weight, and the orders (by reason, a year after the first buy, the busiest
    30 days)."""
    money = holdmix.money_metrics(result, costs)
    pos = result["position"].to_numpy(dtype=float)[1:]
    return {
        "DD": down_day(_returns(result)),
        "F": -money["max_drawdown"],
        "worst_week": money["worst_week"],
        "worst_day": money["worst_day"],
        "over_cap": _over_cap(result, _frac(s, "s") * _real(w, "w", 0.0, low_inclusive=False)),
        "cagr": _cagr(result),
        "fees_pct_per_year": money["fees_pct_per_year"],
        "gas_pct_per_year": money["gas_pct_per_year"],
        "first_cost_pct": money["first_cost_pct"],
        "realised": math.fsum(pos.tolist()) / len(pos),
        **_trading(result),
    }


def _longest(q: np.ndarray, index: pd.DatetimeIndex) -> float:
    times = index.asi8
    n = len(q)
    best, t = 0.0, 0
    while t < n:
        if q[t] < 1.0:
            a = t
            while t < n and q[t] < 1.0:
                t += 1
            end = t if t < n else n - 1
            best = max(best, (int(times[end]) - int(times[a])) / DAY_US)
        else:
            t += 1
    return best


def missed_rebound(rule_ret, n_ret, index, i_close) -> float:
    """The gap (points) after the worst low of I (READINGS_PINNED["rebound"])."""
    i = np.asarray(i_close, dtype=float)
    times = pd.DatetimeIndex(index).asi8
    low = int(np.argmin(i))
    later = np.flatnonzero(times >= times[low] + REBOUND_DAYS * DAY_US)
    end = int(later[0]) if len(later) else len(i) - 1
    a = np.asarray(n_ret, dtype=float)[low + 1 : end + 1]
    b = np.asarray(rule_ret, dtype=float)[low + 1 : end + 1]
    return 100.0 * (float(np.prod(1.0 + a)) - float(np.prod(1.0 + b)))


def rule_measures(qp: QPath, rule: pd.DataFrame, n_run: pd.DataFrame, i_close) -> dict:
    """The rule's stepping-back numbers (section 8): the share of rows 0 .. n-2 with q < 1 and with q <= 0.5, the
    longest stretch with q < 1 in days, the step-downs and step-ups, whether any decision stepped back, and the
    missed rebound against N."""
    q = np.asarray(qp.q, dtype=float)
    head = q[:-1]
    before = q[qp.checks - 1] if len(qp.checks) else np.zeros(0)
    return {
        "q_lt1": float((head < 1.0).mean()),
        "q_le_half": float((head <= 0.5).mean()),
        "longest_back_days": _longest(q, rule.index),
        "step_downs": int((qp.q_checks < before).sum()),
        "step_ups": int((qp.q_checks > before).sum()),
        "steps_back": bool(qp.q_on < 1.0 or (qp.q_checks < 1.0).any()),
        "rebound_gap": missed_rebound(rule["ret"].to_numpy(), n_run["ret"].to_numpy(), rule.index, i_close),
    }


def compare(rule: Mapping, n: Mapping, x: Mapping, x_eq: Mapping | None) -> dict:
    """V_X, V_N (None when a DD is 0) and the costs c_N, c_X, c_eq in points a year (positive: the tool earned less;
    c_eq None without X_eq), from :func:`run_measures` outputs."""
    return {
        "V_X": ride_v(rule["DD"], x["DD"]),
        "V_N": ride_v(rule["DD"], n["DD"]),
        "c_N": 100.0 * (n["cagr"] - rule["cagr"]),
        "c_X": 100.0 * (x["cagr"] - rule["cagr"]),
        "c_eq": None if x_eq is None else 100.0 * (x_eq["cagr"] - rule["cagr"]),
        "realised_gap": rule["realised"] - x["realised"],
    }


# ------------------------------------------------------------------------------------------------ the statistics


def index_set(
    n: int, *, resamples: int = RESAMPLES, mean_block: float = MEAN_BLOCK, seed: int = RESAMPLE_SEED
):
    """The paired resampling's index sets (section 9.2): ``resamples`` draws of
    ``stationary_bootstrap_indices(n, mean_block, rng)`` from one ``default_rng(seed)``, in order (int32 rows)."""
    n, resamples = _count(n, "n", 1), _count(resamples, "resamples", 1)
    rng = np.random.default_rng(_count(seed, "seed"))
    out = np.empty((resamples, n), dtype=np.int32)
    for b in range(resamples):
        out[b] = stationary_bootstrap_indices(n, mean_block, rng)
    return out


def resampled_means(values, idx, chunk: int = 1000) -> np.ndarray:
    """mean(values[idx_b]) for each resample b (numpy's mean, row by row)."""
    d = np.asarray(values, dtype=float)
    idx = np.asarray(idx)
    if idx.ndim != 2 or idx.shape[1] != len(d):
        raise ValueError("resampled_means: one index row per resample, as long as the values")
    out = np.empty(len(idx))
    for i in range(0, len(idx), chunk):
        out[i : i + chunk] = d[idx[i : i + chunk]].mean(axis=1)
    return out


def _p(count: int, b: int) -> float:
    return (1 + count) / (b + 1)


def risk_x(r_rule, r_x, idx, *, keep: bool = False) -> dict:
    """RISK-X and the cost flag (sections 9.2, 9.5) on paired return rows: V, V* per resample, its 90% interval,
    p_calm, p_rough, p_eq, g, g*'s p and the flag. ``missing`` names why the cell is MISSING (a zero DD or a resample
    with a zero mean), else None (and then every number is set). ``keep=True`` adds the V* array (``V_star``)."""
    a, b = np.asarray(r_rule, dtype=float), np.asarray(r_x, dtype=float)
    if a.shape != b.shape or a.ndim != 1:
        raise ValueError("risk_x: two return series of one length")
    out = dict.fromkeys(("V", "V_lo", "V_hi", "p_calm", "p_rough", "p_eq", "g", "cost_p"), None)
    out.update(cost_flag=None, missing=None)
    v = ride_v(down_day(a), down_day(b))
    if v is None:
        out["missing"] = "a DD of 0"
        return out
    ma = resampled_means(np.minimum(a, 0.0) ** 2, idx)
    mb = resampled_means(np.minimum(b, 0.0) ** 2, idx)
    if not ((ma > 0.0).all() and (mb > 0.0).all()):
        out["missing"] = "a resample with a zero mean"
        return out
    vs = 0.5 * (np.log(ma) - np.log(mb))
    diff = np.log1p(a) - np.log1p(b)
    gs = YEAR_DAYS * resampled_means(diff, idx)
    n = len(vs)
    lo, hi = (float(x) for x in np.percentile(vs, INTERVAL))
    cost_p = _p(int((gs >= -COST_MARGIN).sum()), n)
    out.update(
        V=v,
        V_lo=lo,
        V_hi=hi,
        p_calm=_p(int((vs >= 0.0).sum()), n),
        p_rough=_p(int((vs <= 0.0).sum()), n),
        p_eq=_p(int((vs <= EQ_BOUND).sum()), n),
        g=YEAR_DAYS * math.fsum(diff.tolist()) / len(diff),
        cost_p=cost_p,
        cost_flag=bool(cost_p < ALPHA),
    )
    if keep:
        out["V_star"] = vs
    return out


def holm(pvalues: Mapping) -> dict:
    """Holm over a (pool, mix) family (section 9.2): the p's sorted, setting (i) passes when p_(j) < 0.05 / (m + 1 -
    j) for every j <= i (strict). A MISSING (None) p makes every outcome MISSING (READINGS_PINNED["holm_missing"])."""
    if any(not _finite(p) for p in pvalues.values()):
        return dict.fromkeys(pvalues, None)
    m = len(pvalues)
    out, passing = {}, True
    for j, (key, p) in enumerate(sorted(pvalues.items(), key=lambda kv: kv[1])):
        passing = passing and p < ALPHA / (m - j)
        out[key] = passing
    return out


def e1(v0, v_copies: Sequence) -> dict:
    """RISK-E1 (section 9.3): rank p = (1 + #{V_u <= V_0}) / (1 + copies), ties against the rule; holds by
    ``trend.rank_holds``. A MISSING V gives ``holds`` None."""
    vs = list(v_copies)
    if not _finite(v0) or not vs or any(not _finite(v) for v in vs):
        return {"rank_p": None, "at_or_below": None, "copies": len(vs), "holds": None}
    below = sum(1 for v in vs if v <= v0)
    rank_p = (1 + below) / (1 + len(vs))
    return {"rank_p": rank_p, "at_or_below": below, "copies": len(vs), "holds": trend.rank_holds(rank_p)}


def ride_label(*, missing: bool, steps: bool, v, p_rough, p_eq, holm_pass, e1_holds) -> str:
    """Section 9.4's label, checked in its order (READINGS_PINNED["label_missing"])."""
    if missing or not all(_finite(x) for x in (v, p_rough, p_eq)):
        return MISSING
    if not steps:
        return NOT_STEPPING
    if p_rough < ALPHA:
        return ROUGHER
    if v < 0.0:
        needs = (holm_pass, e1_holds)
        if False not in needs:
            if None in needs:
                return MISSING
            return BELOW_NOTICE if p_eq < ALPHA else CALMER
    if p_eq < ALPHA:
        return NO_DIFFERENCE
    return CANT_TELL


def label_family(cells: Sequence[Mapping]) -> list[dict]:
    """Holm and the labels of one (pool, rowset, mix) family: each cell has ``w``, ``missing``, ``steps`` and
    :func:`risk_x`'s and :func:`e1`'s numbers (``e1_holds``). Returns the cells with ``holm`` and ``label``."""
    pvals = {c["w"]: (1.0 if not c["steps"] and not c["missing"] else c["p_calm"]) for c in cells}
    passed = holm(pvals)
    out = []
    for c in cells:
        lab = ride_label(
            missing=bool(c["missing"]),
            steps=bool(c["steps"]),
            v=c["V"],
            p_rough=c["p_rough"],
            p_eq=c["p_eq"],
            holm_pass=passed[c["w"]],
            e1_holds=c["e1_holds"],
        )
        out.append({**c, "holm": passed[c["w"]], "label": lab})
    return out


# ------------------------------------------------------------------------------------------------ the rules


def _and3(values: Sequence) -> bool | None:
    if False in values:
        return False
    return None if None in values else True


def _median(values) -> float:
    return float(np.median(np.asarray(values, dtype=float)))


def d1(windows: pd.DataFrame, labels: pd.DataFrame, *, settings=W_VALUES, mixes=MIXES) -> dict:
    """D1, the suggested default on one pool (section 10). ``windows``: the pool's window runs (columns ``kind``,
    ``status``, ``w``, ``s``, ``f``, ``window``, and on the rule rows ``V_X`` and ``c_X``); ``labels``: one row per (w,
    s, f) with ``label`` and ``failed`` (a run of the cell's full span failed, an X_eq excepted). ``default`` is a w,
    :data:`NO_DEFAULT` or :data:`MISSING` (READINGS_PINNED["d1_missing"])."""
    out = {"default": MISSING, "reason": None, "windows": None, "settings": []}
    failed = (windows["status"].to_numpy() != OK) & (windows["kind"].to_numpy() != "X_eq")
    if failed.any() or labels["failed"].astype(bool).any():
        out["reason"] = "a run of the pool failed (stop rule 4)"
        return out
    rules = windows[windows["kind"].to_numpy() == "rule"]
    n = len(set(rules["window"].tolist()))
    out["windows"] = n
    for w in settings:
        per_mix, results, first = [], [], None
        for s, f in mixes:
            mine = rules[
                (rules["w"] == w).to_numpy() & (rules["s"] == s).to_numpy() & (rules["f"] == f).to_numpy()
            ]
            lab = labels[
                (labels["w"] == w).to_numpy() & (labels["s"] == s).to_numpy() & (labels["f"] == f).to_numpy()
            ]
            if len(mine) != n or len(lab) != 1:
                raise ValueError(
                    f"d1: setting {w} at mix {(s, f)} does not hold one run per window and one label"
                )
            vx = mine["V_X"].to_numpy(dtype=float)
            calmer = int((vx < 0.0).sum())
            r1 = None if np.isnan(vx).any() else bool(2 * calmer >= n)
            label = str(lab["label"].iloc[0])
            r2 = None if label == MISSING else label in D1_LABELS
            c_med = _median(mine["c_X"])
            r3 = None if math.isnan(c_med) else bool(c_med <= COST_MARGIN_POINTS)
            for rule, r in ((1, r1), (2, r2), (3, r3)):
                if r is False and first is None:
                    first = {"mix": (s, f), "rule": rule}
            results += [r1, r2, r3]
            per_mix.append(
                {
                    "s": s,
                    "f": f,
                    "calmer_windows": calmer,
                    "label": label,
                    "c_X_median": c_med,
                    "rules": [r1, r2, r3],
                }
            )
        out["settings"].append(
            {
                "w": w,
                "usable": _and3(results),
                "calmer_all": all(m["label"] == CALMER for m in per_mix),
                "first_failure": first,
                "mixes": per_mix,
            }
        )
    if any(st["usable"] is None for st in out["settings"]):
        out["reason"] = "a setting's rules are MISSING"
        return out
    usable = [st for st in out["settings"] if st["usable"]]
    if not usable:
        out.update(default=NO_DEFAULT, reason="no usable setting")
        return out
    pick = max(usable, key=lambda st: (st["calmer_all"], st["w"]))
    out.update(default=pick["w"], reason="usable: " + ", ".join(str(st["w"]) for st in usable))
    return out


def d2(headline: Mapping, checks: Mapping[str, Mapping | None]) -> dict:
    """D2's robustness label (section 10, buy-the-dip's rules): each check is a :func:`d1` output or None (MISSING).
    Order: NOT ROBUST before MISSING before ROBUST."""
    mine = headline["default"]
    per, moved, missing = {}, [], []
    for name, check in checks.items():
        theirs = per[name] = MISSING if check is None else check["default"]
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


def describe(values) -> dict:
    """n, the 10th, 50th and 90th percentiles (linear) and the share above 0 of the finite values."""
    x = np.asarray([v for v in values if _finite(v)], dtype=float)
    if not len(x):
        return {"n": 0, "p10": None, "median": None, "p90": None, "share_above_0": None}
    p10, med, p90 = (float(v) for v in np.percentile(x, DESCRIBE_PERCENTILES))
    return {"n": len(x), "p10": p10, "median": med, "p90": p90, "share_above_0": float((x > 0.0).mean())}


def _falls(values, budget: float | None) -> dict:
    x = np.asarray(values, dtype=float)
    return {
        "median": _median(x),
        "Q": float(np.percentile(x, FALL_PERCENTILE)),
        "worst": float(x.max()),
        "past_budget": None if budget is None else float((x > budget).mean()),
    }


def _cut(v) -> float | None:
    return None if not _finite(v) else 100.0 * (1.0 - math.exp(v))


def d3_cell(runs: pd.DataFrame, budget: float | None) -> dict:
    """D3 over one cell's window runs (section 10): V_X and V_N with their cuts, c_N, c_X, c_eq, x, x_eq, fees, the
    falls of the rule, N and X against the budget, the worst week, the over-cap weeks, the time stepped back, the
    missed rebound, the trades, and the core numbers by the year of each window's first close."""
    by = {k: runs[runs["kind"].to_numpy() == k].sort_values("window") for k in ("rule", "N", "X")}
    rule = by["rule"]
    out = {key: describe(rule[key]) for key in ("V_X", "V_N", "c_N", "c_X", "c_eq", "x", "x_eq")}
    out["cut_X"] = describe([_cut(v) for v in rule["V_X"]])
    out["cut_N"] = describe([_cut(v) for v in rule["V_N"]])
    out["fees_pct_per_year"] = describe(rule["fees_pct_per_year"])
    out["F"] = {k: _falls(by[k]["F"], budget) for k in by}
    out["worst_week"] = {k: float(by[k]["worst_week"].min()) for k in by}
    out["over_cap"] = {k: describe(by[k]["over_cap"]) for k in by}
    out["stepped_back"] = describe(rule["q_lt1"])
    out["longest_back_days"] = describe(rule["longest_back_days"])
    out["rebound_gap"] = {"median": _median(rule["rebound_gap"]), "worst": float(rule["rebound_gap"].max())}
    out["orders_per_year"] = describe(rule["orders_per_year"])
    out["busiest_30d"] = int(rule["busiest_30d"].max())
    out["windows"] = len(rule)
    out["calmer_windows"] = int((rule["V_X"].to_numpy(dtype=float) < 0.0).sum())
    out["by_year"] = {
        int(y): {
            "V_X": _median(part["V_X"]),
            "c_N": _median(part["c_N"]),
            "F": _median(part["F"]),
        }
        for y, part in rule.groupby("year")
    }
    return out


def d3(windows: pd.DataFrame, spans: pd.DataFrame, default, budget: float | None) -> dict:
    """D3 for every cell of a pool: :func:`d3_cell` over its windows and its full-span row (``spans``: one row per
    (w, s, f) with the span statistics and the label), the default's cells marked."""
    cells = []
    for (w, s, f), runs in windows.groupby(["w", "s", "f"], sort=True):
        span = spans[
            (spans["w"] == w).to_numpy() & (spans["s"] == s).to_numpy() & (spans["f"] == f).to_numpy()
        ]
        cells.append(
            {
                "w": float(w),
                "s": float(s),
                "f": float(f),
                "default": bool(w == default),
                "windows": d3_cell(runs, budget),
                "span": span.iloc[0].to_dict() if len(span) else None,
            }
        )
    return {"default": default, "budget": budget, "cells": cells}
