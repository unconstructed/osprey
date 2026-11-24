"""downvol-steady: the downside-volatility-scaled hold (``research/downvol-steady/PLAN.md``).

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the reference
rebalancer, through :func:`lab.runner.trend.run_states`, not NautilusTrader (AGENTS.md hard rule 3). PLAN.md is the
contract; "VP n" is section n of ``research/vol-steady/PLAN.md`` (at ``ea1426e``), which applies unless PLAN.md changes
it. No existing file is changed: the rule is vol-steady's (:mod:`lab.runner.volsteady`: the basket return, m, q, the
Monday checks, the encoding, R_0's stitched schedule, P, the plateau, the verdict and headline) with ONE measure swapped
in through a small seam (``window=``), plus the q-only shift of E1 (amendment M1). The executor, the whole-schedule
shift, N0, X and the luck statistics are :mod:`lab.runner.trend`'s.

The measure (sections 3-4)
--------------------------
The **downside deviation around zero** at close c for lookback L (:func:`sigma_down`): the window is the basket returns
x over rows c - L + 1 .. c (L rows; ``volsteady.basket_returns``); d_t = ``min(x_t, 0.0)``; ss = ``math.fsum(d * d)``,
one exactly rounded sum per window (never a running sum); sigma = ``sqrt(365) * math.sqrt(2.0 * ss / L)``: around zero,
not the window's mean; over L, not L - 1; the factor 2 makes it about equal to vol-steady's sigma for returns symmetric
around zero, so tau keeps its meaning. It exists only from c >= L, as vol-steady's does. A window with no down day gives
0, so m = 1 (``volsteady.scale``): the full share.

The seam
--------
:func:`downvol_path`, :class:`DownVolStream`, :func:`sigma_down` and :func:`downvol_backtest` are vol-steady's
``vol_path``, ``VolStream``, ``sigma_hat`` and ``vol_backtest`` with the per-window measure passed in (``window=``, a
function of the window's list of L returns). The default is :func:`downside`; with ``window=volsteady._sigma`` each
equals vol-steady's bit for bit (tested), which pins that only the measure differs.

E1 with the share held fixed (amendment M1)
-------------------------------------------
:func:`stitched_steps` builds R_0's schedule (``volsteady.stitched_schedule``) and keeps, for each of its W check closes
c_k, the step q(c_k) and the s of the fold holding c_k; it checks that the schedule's share is exactly s x q there.
:func:`q_shifted` is E1's null for shift u: ``share_u(c_k) = s_fold(c_k) * q(c_((k + u) mod W))``. The state pair z
(the rule's activation, (1, 1) at every check of a train or validate span, since activation comes before t0) moves with
q; s, the fold and the check closes stay; the rows before c_0 are unchanged; no price is read. With one s in every fold
it is ``trend.shifted`` (the whole-schedule shift, reported as the description E1-whole) bit for bit. :func:`run_q_shift`
runs it through ``trend.run_span``, one book from row 0, as R_0 and the whole-schedule shifts are run.

pandas caveat (as in portfolio.py and trend.py): ``attrs`` holds arrays and frames; drop them before ``pd.concat``.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.runner.portfolio import ASSETS, validate_panel
from lab.runner.reference import Costs, _real

__all__ = [
    "DownVolStream",
    "StepSchedule",
    "downside",
    "downvol_backtest",
    "downvol_path",
    "q_shifted",
    "run_q_shift",
    "sigma_down",
    "stitched_steps",
]

WEEKDAY = V.WEEKDAY
F_SPLIT = V.F_SPLIT
DOWN_FACTOR = 2.0  # sigma_down = sqrt(365) x sqrt(2 x ss / L) (section 3-4)

Window = Callable[[list], float]


# ------------------------------------------------------------------------------------------------ the measure


def downside(window: list[float]) -> float:
    """sqrt(365) x sqrt(2 x fsum(min(x, 0)^2) / L) over the window's L returns (module docstring)."""
    n = len(window)
    ss = math.fsum(d * d for d in (min(v, 0.0) for v in window))
    return V.SQRT_365 * math.sqrt(DOWN_FACTOR * ss / n)


def sigma_down(x, lookback, rows=None, *, window: Window = downside) -> np.ndarray:
    """The measure at each close c >= L over x[c - L + 1 .. c], per window; NaN before row L (and, with ``rows``, on
    every row not asked for: the values are the same either way). ``x`` is ``volsteady.basket_returns``' output."""
    a = np.asarray(x, dtype=float)
    n_rows = V._count(lookback, "lookback", V.MIN_LOOKBACK)
    if a.ndim != 1 or not np.isfinite(a[1:]).all():
        raise ValueError("x must be a 1-D array of finite basket returns from row 1 on")
    n = len(a)
    out = np.full(n, np.nan)
    values = a.tolist()
    todo = range(n_rows, n) if rows is None else np.asarray(rows, dtype=np.int64).tolist()
    for c in todo:
        if not 0 <= c < n:
            raise ValueError(f"row {c} is outside the {n} closes")
        if c >= n_rows:
            out[c] = window(values[c - n_rows + 1 : c + 1])
    return out


def downvol_path(
    bars: pd.DataFrame, lookback, target_vol, crypto_share, *, weekday=WEEKDAY, window: Window = downside
) -> V.VolPath:
    """The share path of the rule on a panel: ``volsteady.vol_path`` with the measure ``window`` (default the
    downside deviation). The share at close t depends on closes 0..t only; ``VolPath.sigma`` holds the measure."""
    validate_panel(bars)
    n_rows = V._count(lookback, "lookback", V.MIN_LOOKBACK)
    tau = _real(target_vol, "target_vol", 0.0, low_inclusive=False)
    s = _real(crypto_share, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    day = T._weekday(weekday)
    checks = T.check_closes(bars.index, day, n_rows)
    sig = sigma_down(V.basket_returns(bars), n_rows, rows=checks, window=window)
    n = len(bars)
    z = np.zeros((n, len(ASSETS)), dtype=np.int8)
    share = np.zeros(n)
    q = np.zeros(n)
    for c in checks.tolist():
        qc = V.quarter(V.scale(float(sig[c]), tau))
        share[c:] = s * qc
        q[c:] = qc
    if len(checks):
        z[int(checks[0]) :] = 1
    return V.VolPath(z, share, q, sig, checks, int(checks[0]) if len(checks) else None)


class DownVolStream:
    """The live rule: fed one close at a time, it gives the share in force that :func:`downvol_path` gives on the panel
    of those closes, bit for bit (the same basket return, the same ``math.fsum``, the same q)."""

    def __init__(self, lookback, target_vol, crypto_share, *, weekday=WEEKDAY, window: Window = downside):
        self.lookback = V._count(lookback, "lookback", V.MIN_LOOKBACK)
        self.target_vol = _real(target_vol, "target_vol", 0.0, low_inclusive=False)
        self.crypto_share = _real(
            crypto_share, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True
        )
        self.weekday = T._weekday(weekday)
        self.window = window
        self._x: deque[float] = deque(maxlen=self.lookback)
        self._row = -1
        self._last: pd.Timestamp | None = None
        self._prev: tuple[float, float] | None = None
        self.share = 0.0
        self.q = 0.0
        self.sigma = math.nan

    def update(self, ts, close_btc, close_eth) -> float:
        """Add the close at ``ts`` (tz-aware, strictly after the previous one); returns the share in force at it."""
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
            self._x.append(math.log1p(0.5 * (cb / pb - 1.0) + 0.5 * (ce / pe - 1.0)))
        self._prev = (cb, ce)
        if self._row >= self.lookback and (self.weekday is None or stamp.day_of_week == self.weekday):
            self.sigma = self.window(list(self._x))
            self.q = V.quarter(V.scale(self.sigma, self.target_vol))
            self.share = self.crypto_share * self.q
        return self.share


def downvol_backtest(
    params: Mapping,
    bars: pd.DataFrame,
    *,
    limits: Mapping,
    costs: Costs,
    f=F_SPLIT,
    weekday=WEEKDAY,
    window: Window = downside,
) -> pd.DataFrame:
    """The ``BacktestFn``: ``volsteady.vol_backtest`` with the measure ``window`` (default the downside deviation).
    The params are vol-steady's (``volsteady.parse_params``: lookback, target_vol, crypto_share). Bind ``limits`` and
    ``costs`` with ``functools.partial`` (picklable). Adds ``z``, ``share``, ``q``, ``sigma`` (the measure),
    ``checks`` and ``activation`` to the attrs."""
    p = V.parse_params(params)
    path = downvol_path(
        bars, p["lookback"], p["target_vol"], p["crypto_share"], weekday=weekday, window=window
    )
    result = T.run_states(
        bars, T.in_force(path.z, path.share, f=f), limits=limits, costs=costs, states=path.z
    )
    result.attrs["z"] = path.z
    result.attrs["share"] = path.share
    result.attrs["q"] = path.q
    result.attrs["sigma"] = path.sigma
    result.attrs["checks"] = path.checks
    result.attrs["activation"] = path.activation
    return result


# ------------------------------------------------------------------------------------------------ E1 with s held


class StepSchedule(NamedTuple):
    """R_0's schedule and, at each of its W check closes, the step q and the s of the fold holding the close."""

    schedule: T.Schedule
    q: np.ndarray  # (W,) q_i(c_k)
    s: np.ndarray  # (W,) s_i of the fold i holding c_k


def stitched_steps(
    index,
    windows,
    fold_z: Sequence,
    fold_shares: Sequence,
    fold_q: Sequence,
    shares: Sequence,
    *,
    weekday=WEEKDAY,
) -> StepSchedule:
    """``volsteady.stitched_schedule`` (R_0's schedule, its head fold 0's per-row share) with each check's q (from
    ``fold_q``, each fold's q path on rows 0 .. last_i) and its fold's s (``shares``). Refuses unless the schedule's
    share at every check is exactly s x q."""
    sched = V.stitched_schedule(index, windows, fold_z, fold_shares, weekday=weekday)
    if len(fold_q) != len(fold_shares) or len(shares) != len(fold_shares):
        raise ValueError("stitched_steps: one q path and one s per fold")
    s_fold = [
        _real(s, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True) for s in shares
    ]
    q_fold = []
    for i, (q, sh) in enumerate(zip(fold_q, fold_shares, strict=True)):
        a = np.asarray(q, dtype=float)
        if a.shape != np.shape(sh) or not np.isin(a, V.QUARTERS).all():
            raise ValueError(f"fold {i} q must be one step in {V.QUARTERS} per row of its share path")
        q_fold.append(a)
    q = np.array([q_fold[i][c] for c, i in zip(sched.checks.tolist(), sched.fold.tolist(), strict=True)])
    s = np.array([s_fold[i] for i in sched.fold.tolist()])
    bad = np.flatnonzero(sched.share != s * q)
    if len(bad):
        k = int(bad[0])
        raise ValueError(
            f"stitched_steps: the share in force at check close row {int(sched.checks[k])} (fold "
            f"{int(sched.fold[k])}) is not its fold's s x q"
        )
    return StepSchedule(sched, q, s)


def q_shifted(steps: StepSchedule, u: int) -> T.Schedule:
    """E1's null for shift u (amendment M1): ``share_u(c_k) = s_fold(c_k) * q(c_((k + u) mod W))``, z moving with q;
    s, the fold, the check closes and the rows before c_0 unchanged. No price is read."""
    w = len(steps.q)
    u = V._count(u, "u", 0)
    if u >= w:
        raise ValueError(f"u must be in 0..{w - 1}, got {u}")
    order = (np.arange(w) + u) % w
    sched = steps.schedule
    return sched._replace(z=sched.z[order], share=steps.s * steps.q[order])


def run_q_shift(
    bars: pd.DataFrame, steps: StepSchedule, *, limits: Mapping, costs: Costs, f=F_SPLIT, u: int = 0
) -> pd.DataFrame:
    """The q-only shift u run as one book from row 0 (``trend.run_span``); u = 0 is R_0."""
    return T.run_span(bars, q_shifted(steps, u), limits=limits, costs=costs, f=f)
