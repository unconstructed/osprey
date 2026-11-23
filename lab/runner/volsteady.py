"""vol-steady: the volatility-scaled hold, encoded in trend-steady's one executor (``research/vol-steady/PLAN.md``).

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the reference
rebalancer, through :func:`lab.runner.trend.run_states`, not NautilusTrader (AGENTS.md hard rule 3). PLAN.md is the
contract; section numbers below are that file's, and "TP n" is section n of ``research/trend-steady/PLAN.md``. No
existing file is changed: the executor, the schedule shift, the comparators (N0, X), the luck statistics and the gates
are imported from :mod:`lab.runner.trend`; the few helpers that must differ are written here and tested here.

The rule (section 4)
--------------------
- **The basket return** at close t >= 1: b_t = 0.5 * (C_BTC,t / C_BTC,t-1 - 1.0) + 0.5 * (C_ETH,t / C_ETH,t-1 - 1.0),
  x_t = ``math.log1p(b_t)`` (ln(1 + b_t); :func:`basket_returns`). A missing close (Kraken's 2018-01-13) makes one
  2-day row, one return, unscaled.
- **The volatility** at close c for lookback L (:func:`sigma_hat`): the window is x over rows c - L + 1 .. c (L rows,
  not L days); mean = ``math.fsum(window) / L``; ss = ``math.fsum(d * d for d = x - mean)``; sd = ``math.sqrt(ss /
  (L - 1))`` (ddof 1); sigma = ``math.sqrt(365.0) * sd``. Two passes, once per window, never a running sum, so the
  batch and the live :class:`VolStream` agree bit for bit. It exists only from c >= L (x starts at row 1).
- **The share:** m = 1.0 if sigma == 0 else ``min(1.0, target_vol / sigma)`` (:func:`scale`); q =
  ``math.floor(m * 4.0 + 1e-9) / 4.0`` (:func:`quarter`), so q in {0, 0.25, 0.5, 0.75, 1}; the crypto share in force
  from check close c is ``crypto_share * q``.
- **Check closes:** the rows c >= L whose close falls on ``weekday`` (Monday 00:00 UTC by default;
  ``trend.check_closes(index, weekday, L)``); ``weekday=None`` is the daily-check description. The first of them is
  the **activation** close. Before it the share is 0 (all USDC, TP's "start out").
- **The encoding** (section 4): z = (1, 1) on every row from the activation close on and (0, 0) before; the share in
  force per row is the latest check's ``s * q`` (0 before activation); the targets are ``trend.in_force(z, share)``,
  i.e. (s q / 2, s q / 2). :func:`vol_backtest` hands them to ``trend.run_states`` with ``states=z``, so run_states'
  reason labels read: ``switch`` = the activation order (z turning on with a non-zero share), ``re-cut`` = every other
  change of the vector in force (a quarter step, or a change of s between source folds in R_0), ``limit`` = a limit
  fix. They only label; they never decide.

R_0 and its shifts (section 9)
-----------------------------
:func:`stitched_schedule` builds a ``trend.Schedule`` from S's fold runs: at each Monday check close c_k of fold i's
test span [t0_i, last_i], the entry is fold i's z(c_k) and its share in force ``s_i * q_i(c_k)`` (so a shift moves the
whole share path, each entry carrying its fold's s). The rows before c_0 are fold 0's, row by row: ``head_z`` is fold
0's z there and ``head_share`` is **fold 0's per-row share array** (not one float as in the trend rule, whose share
before c_0 is constant). ``trend.span_targets`` builds its head with ``np.full(c_0, head_share)``, which takes the
array as it is (numpy broadcasts an array fill value), so ``trend.shifted``, ``trend.span_targets`` and
``trend.run_span`` run unchanged (tested here).

P, the minimum-information floor (section 11)
---------------------------------------------
:func:`power_count`: per fold run, the share changes (rows t with share(t) != share(t - 1), exact float comparison,
the share before row 0 being 0) at check closes whose orders fill in the fold's kept rows (t0_i <= t <= last_i - 1).
**Pinned reading:** each fold run's first share change (always from the start share 0: the first buy, at activation
or at the first later check with q > 0) is not counted. Re-cuts between folds (R_0 only) and limit fixes never enter:
P reads S's fold runs' share paths, not their orders. Holds if the total is >= 20 with at least one in each of at least
4 of the 5 folds.

pandas caveat (as in portfolio.py and trend.py): ``attrs`` holds arrays and frames; drop them before ``pd.concat``.
"""

from __future__ import annotations

import math
import numbers
from collections import deque
from collections.abc import Mapping, Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

from lab.runner import trend as T
from lab.runner.portfolio import ASSETS, validate_panel
from lab.runner.reference import Costs, _check_params, _param_float, _param_int, _real
from lab.search.space import Param

__all__ = [
    "ALLOWED_S",
    "BOX",
    "CALIBRATION_POINTS",
    "FIRST_ACTIVE_ROW",
    "PARAM_NAMES",
    "QUARTERS",
    "SPECS",
    "TIMING_KEYS",
    "VolPath",
    "VolStream",
    "basket_returns",
    "check_feasibility",
    "check_shares",
    "first_check",
    "headline",
    "measurement_points",
    "parse_params",
    "plateau_step",
    "plateau_steps",
    "power_count",
    "project_cpu_minutes",
    "quarter",
    "reported_verdict",
    "scale",
    "sigma_hat",
    "stitched_schedule",
    "verdict",
    "vol_backtest",
    "vol_path",
]

# ------------------------------------------------------------------------------------------------ pinned values

WEEKDAY = T.WEEKDAY  # Monday 00:00 UTC (the bar of Sunday)
F_SPLIT = T.F_SPLIT  # BTC/ETH 50/50, fixed (section 5)
HEADROOM = T.HEADROOM
PARAM_NAMES = ("lookback", "target_vol", "crypto_share")
SPECS = (
    Param("lookback", "int", 10, 120, log=True),
    Param("target_vol", "float", 0.30, 1.20, log=True),
    Param("crypto_share", "float", 0.30, 0.60),
)
BOX = {p.name: (float(p.low), float(p.high)) for p in SPECS}
ALLOWED_S = T.ALLOWED_S  # (0.30, 0.40, 0.50, 0.60): the customer setting (Branch R, section 8)
PLATEAU_SHARE_EXTREMES = T.PLATEAU_SHARE_EXTREMES  # (0.24, 0.72)
QUARTERS = (0.0, 0.25, 0.5, 0.75, 1.0)
Q_TOL = 1e-9  # q = floor(m * 4 + 1e-9) / 4 (section 4)
ANNUAL_DAYS = 365.0
SQRT_365 = math.sqrt(ANNUAL_DAYS)
MIN_LOOKBACK = 2  # a sample sd (ddof 1) needs two returns
FIRST_ACTIVE_ROW = 15  # L = 10 first checks at row 14 (2017-01-16), filled at row 15 (section 5)
CALIBRATION_POINTS = ((10, 0.80, 0.50), (120, 0.80, 0.50))  # (L, tau, s), the slow tier (section 9)
TIMING_KEYS = ("study", "run", "bootstrap")  # what the projection guard re-times (no stop runs: section 11A)
WINDOW_DAYS = T.WINDOW_DAYS
MIN_CHANGES = T.MIN_SWITCHES  # P: 20 share changes
MIN_CHANGE_FOLDS = T.MIN_SWITCH_FOLDS  # in at least 4 of the 5 folds
INSIDE, OUTSIDE = T.INSIDE, T.OUTSIDE
NO_EDGE, INCONCLUSIVE, EDGE = T.NO_EDGE, T.INCONCLUSIVE, T.EDGE
TRIGGERS = T.TRIGGERS


def _count(value, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


# ------------------------------------------------------------------------------------------------ the signal


def basket_returns(bars: pd.DataFrame) -> np.ndarray:
    """x_t = log1p(0.5 * (C_BTC,t / C_BTC,t-1 - 1) + 0.5 * (C_ETH,t / C_ETH,t-1 - 1)) for t >= 1; NaN at row 0."""
    validate_panel(bars)
    cb = bars[(ASSETS[0], "close")].to_numpy(dtype=float).tolist()
    ce = bars[(ASSETS[1], "close")].to_numpy(dtype=float).tolist()
    out = [math.nan]
    for t in range(1, len(cb)):
        out.append(math.log1p(0.5 * (cb[t] / cb[t - 1] - 1.0) + 0.5 * (ce[t] / ce[t - 1] - 1.0)))
    return np.asarray(out, dtype=float)


def _sigma(window: list[float]) -> float:
    """sqrt(365) x the sample sd (ddof 1) of ``window``: two ``math.fsum`` passes (module docstring)."""
    n = len(window)
    mean = math.fsum(window) / n
    ss = math.fsum((v - mean) * (v - mean) for v in window)
    return SQRT_365 * math.sqrt(ss / (n - 1))


def sigma_hat(x, lookback, rows=None) -> np.ndarray:
    """sigma(c) over x[c - L + 1 .. c] (:func:`_sigma`), per window; NaN before row L (and, with ``rows``, on every row
    not asked for: the values are the same either way). ``x`` is :func:`basket_returns`' output (x[0] is NaN)."""
    a = np.asarray(x, dtype=float)
    n_rows = _count(lookback, "lookback", MIN_LOOKBACK)
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
            out[c] = _sigma(values[c - n_rows + 1 : c + 1])
    return out


def scale(sigma: float, target_vol: float) -> float:
    """m = 1.0 if sigma == 0, else min(1.0, target_vol / sigma)."""
    s = _real(sigma, "sigma", 0.0, low_inclusive=True)
    tau = _real(target_vol, "target_vol", 0.0, low_inclusive=False)
    return 1.0 if s == 0.0 else min(1.0, tau / s)


def quarter(m: float) -> float:
    """q = ``math.floor(m * 4.0 + 1e-9) / 4.0`` for m in [0, 1] (section 4)."""
    m = _real(m, "m", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    return math.floor(m * 4.0 + Q_TOL) / 4.0


def first_check(index, lookback, weekday=WEEKDAY) -> int | None:
    """The activation row: the first check close c >= L (``trend.check_closes(index, weekday, L)``), or None."""
    rows = T.check_closes(index, weekday, _count(lookback, "lookback", MIN_LOOKBACK))
    return int(rows[0]) if len(rows) else None


class VolPath(NamedTuple):
    """The point-in-time share path of one panel (section 4)."""

    z: np.ndarray  # (n, 2) int8: 1 from the activation close on
    share: np.ndarray  # (n,) the crypto share in force at each close (s * q of the latest check; 0 before)
    q: np.ndarray  # (n,) the q in force at each close (0 before activation)
    sigma: np.ndarray  # (n,) sigma at each check close, NaN elsewhere
    checks: np.ndarray  # int64 rows of the check closes (>= L)
    activation: int | None  # the first check close, or None when the panel holds none


def vol_path(bars: pd.DataFrame, lookback, target_vol, crypto_share, *, weekday=WEEKDAY) -> VolPath:
    """The share path of the rule on a panel (module docstring). The share at close t depends on closes 0..t only."""
    validate_panel(bars)
    n_rows = _count(lookback, "lookback", MIN_LOOKBACK)
    tau = _real(target_vol, "target_vol", 0.0, low_inclusive=False)
    s = _real(crypto_share, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    day = T._weekday(weekday)
    checks = T.check_closes(bars.index, day, n_rows)
    x = basket_returns(bars)
    sig = sigma_hat(x, n_rows, rows=checks)
    n = len(bars)
    z = np.zeros((n, len(ASSETS)), dtype=np.int8)
    share = np.zeros(n)
    q = np.zeros(n)
    for c in checks.tolist():
        qc = quarter(scale(float(sig[c]), tau))
        share[c:] = s * qc
        q[c:] = qc
    if len(checks):
        z[int(checks[0]) :] = 1
    return VolPath(z, share, q, sig, checks, int(checks[0]) if len(checks) else None)


class VolStream:
    """The live rule: fed one close at a time, it gives the share in force that :func:`vol_path` gives on the panel of
    those closes, bit for bit (the same basket return, the same two-pass ``math.fsum``, the same q)."""

    def __init__(self, lookback, target_vol, crypto_share, *, weekday=WEEKDAY):
        self.lookback = _count(lookback, "lookback", MIN_LOOKBACK)
        self.target_vol = _real(target_vol, "target_vol", 0.0, low_inclusive=False)
        self.crypto_share = _real(
            crypto_share, "crypto_share", 0.0, low_inclusive=True, high=1.0, high_inclusive=True
        )
        self.weekday = T._weekday(weekday)
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
        check = self._row >= self.lookback and (self.weekday is None or stamp.day_of_week == self.weekday)
        if check:
            self.sigma = _sigma(list(self._x))
            self.q = quarter(scale(self.sigma, self.target_vol))
            self.share = self.crypto_share * self.q
        return self.share


# ------------------------------------------------------------------------------------------------ the BacktestFn

_PARAMS = frozenset(PARAM_NAMES)


def parse_params(params) -> dict:
    """Strict vol params: ``lookback`` (an integer >= 2), ``target_vol`` (> 0, annualised) and ``crypto_share`` (in
    (0, 1]). Unknown or missing keys raise."""
    p = _check_params("vol", params, _PARAMS)
    return {
        "lookback": _param_int(p, "lookback", minimum=MIN_LOOKBACK),
        "target_vol": _param_float(p, "target_vol", low=0.0, low_inclusive=False),
        "crypto_share": _param_float(
            p, "crypto_share", low=0.0, low_inclusive=False, high=1.0, high_inclusive=True
        ),
    }


def vol_backtest(
    params: Mapping, bars: pd.DataFrame, *, limits: Mapping, costs: Costs, f=F_SPLIT, weekday=WEEKDAY
) -> pd.DataFrame:
    """The ``BacktestFn`` (section 4): the rule on ``bars`` from row 0 through ``trend.run_states``. Bind ``limits``
    and ``costs`` with ``functools.partial`` (picklable). ``weekday=None`` is the daily-check description. Adds
    ``z``, ``share``, ``q``, ``sigma``, ``checks`` and ``activation`` to the attrs."""
    p = parse_params(params)
    path = vol_path(bars, p["lookback"], p["target_vol"], p["crypto_share"], weekday=weekday)
    targets = T.in_force(path.z, path.share, f=f)
    result = T.run_states(bars, targets, limits=limits, costs=costs, states=path.z)
    result.attrs["z"] = path.z
    result.attrs["share"] = path.share
    result.attrs["q"] = path.q
    result.attrs["sigma"] = path.sigma
    result.attrs["checks"] = path.checks
    result.attrs["activation"] = path.activation
    return result


# ------------------------------------------------------------------------------------------------ feasibility


def check_shares(s, limits: Mapping, *, f=F_SPLIT) -> list[float]:
    """Stop rule 12 for crypto share s: every s * q (q in :data:`QUARTERS`) passes ``trend.check_share`` with the limits
    as read and h = 0.02. Returns the shares checked."""
    out = []
    for q in QUARTERS:
        T.check_share(s * q, limits, f=f)
        out.append(s * q)
    return out


def check_feasibility(limits: Mapping, *, f=F_SPLIT) -> list[float]:
    """Stop rule 12 before any bar (section 4): :func:`check_shares` for the box ends, every allowed value and the
    plateau extremes 0.24 and 0.72. Returns every share s * q checked (sorted, distinct)."""
    shares = sorted({*BOX["crypto_share"], *ALLOWED_S, *PLATEAU_SHARE_EXTREMES})
    return sorted({x for s in shares for x in check_shares(s, limits, f=f)})


# ------------------------------------------------------------------------------------------------ R_0's schedule


def _fold_spans(index: pd.DatetimeIndex, windows) -> list[tuple[int, int]]:
    spans = [(T._rows_of(index, t0), T._rows_of(index, last)) for t0, last in map(T._window, windows)]
    if not spans:
        raise ValueError("windows must hold at least one fold")
    for i, (p0, pl) in enumerate(spans):
        if pl <= p0 or (i and p0 != spans[i - 1][1] + 1):
            raise ValueError(
                "fold windows must be contiguous: each t0 the close after the previous fold's last"
            )
    return spans


def _share_array(values, n: int, name: str) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    if a.shape != (n,) or not (np.isfinite(a).all() and (a >= 0).all() and (a <= 1).all()):
        raise ValueError(f"{name} must be {n} shares in [0, 1]")
    return a


def stitched_schedule(
    index, windows, fold_z: Sequence, fold_shares: Sequence, *, weekday=WEEKDAY
) -> T.Schedule:
    """R_0's schedule from S's fold runs (module docstring). ``fold_z`` and ``fold_shares``: each fold's z and share in
    force on its H0 slice, rows 0 .. last_i (a prefix of the span ``index``). The check closes of fold i are its closes
    in [t0_i, last_i] on ``weekday``; z(c_k) and the share s_i q_i(c_k) come from that fold. The head (rows before
    c_0) is fold 0's, row by row, with ``head_share`` an array."""
    idx = pd.DatetimeIndex(index)
    spans = _fold_spans(idx, windows)
    if len(fold_z) != len(spans) or len(fold_shares) != len(spans):
        raise ValueError("stitched_schedule: one z path and one share path per fold")
    checks, zs, ss, folds = [], [], [], []
    for i, ((p0, pl), z, s) in enumerate(zip(spans, fold_z, fold_shares, strict=True)):
        z = T._state_array(z, pl + 1, f"fold {i} z")
        s = _share_array(s, pl + 1, f"fold {i} shares")
        rows = T.check_closes(idx[: pl + 1], weekday, p0)
        checks.append(rows)
        zs.append(z[rows])
        ss.append(s[rows])
        folds.append(np.full(len(rows), i, dtype=np.int64))
    if not len(checks[0]):
        raise ValueError("stitched_schedule: fold 0 must hold the first check close")
    first = int(checks[0][0])
    pl0 = spans[0][1]
    head_z = T._state_array(fold_z[0], pl0 + 1, "fold 0 z")[:first]
    head_share = _share_array(fold_shares[0], pl0 + 1, "fold 0 shares")[:first].copy()
    return T.Schedule(
        np.concatenate(checks),
        np.vstack(zs).astype(np.int8),
        np.concatenate(ss),
        np.concatenate(folds),
        head_z,
        head_share,
    )


# ------------------------------------------------------------------------------------------------ P


def power_count(fold_shares: Sequence, windows, index) -> dict:
    """P (section 11; module docstring): share changes at check closes whose orders fill in the fold's kept rows, each
    fold run's first change (its first buy) not counted. Holds if the total is >= 20 with at least one change in each
    of at least 4 folds. Also ``ups``, ``downs`` and ``to_zero`` (counted changes up, down and down to 0),
    descriptions."""
    idx = pd.DatetimeIndex(index)
    spans = _fold_spans(idx, windows)
    if len(fold_shares) != len(spans):
        raise ValueError("power_count: one share path per fold")
    per_fold, ups, downs, to_zero = [], 0, 0, 0
    for i, ((p0, pl), s) in enumerate(zip(spans, fold_shares, strict=True)):
        s = _share_array(s, pl + 1, f"fold {i} shares")
        prev = np.concatenate([[0.0], s[:-1]])
        rows = np.flatnonzero(s != prev)
        counted = [t for t in rows[1:].tolist() if p0 <= t <= pl - 1]
        per_fold.append(len(counted))
        ups += sum(1 for t in counted if s[t] > prev[t])
        downs += sum(1 for t in counted if s[t] < prev[t])
        to_zero += sum(1 for t in counted if s[t] == 0.0)
    total = sum(per_fold)
    folds_with = sum(1 for c in per_fold if c >= 1)
    return {
        "per_fold": per_fold,
        "total": total,
        "folds_with": folds_with,
        "holds": bool(total >= MIN_CHANGES and folds_with >= MIN_CHANGE_FOLDS),
        "ups": ups,
        "downs": downs,
        "to_zero": to_zero,
    }


# ------------------------------------------------------------------------------------------------ G5 plateau


def plateau_step(params: Mapping, name: str, factor) -> tuple[dict, str]:
    """One G5 step (TP 10): ``lookback`` down = max(1, min(half_up(0.8 L), L - 1)), up = max(half_up(1.2 L), L + 1);
    ``target_vol`` and ``crypto_share`` times the factor, not rounded. The mark is :data:`OUTSIDE` when the stepped
    value leaves the search box, else :data:`INSIDE`."""
    p = parse_params(params)
    if name not in PARAM_NAMES:
        raise ValueError(f"plateau_step: name must be one of {PARAM_NAMES}, got {name!r}")
    factor = _real(factor, "factor", 0.0, low_inclusive=False)
    if factor == 1.0:
        raise ValueError("plateau_step: factor must not be 1")
    value = p[name]
    if name == "lookback":
        new = (
            max(1, min(T._half_up(factor * value), value - 1))
            if factor < 1
            else max(T._half_up(factor * value), value + 1)
        )
    else:
        new = value * factor
    low, high = BOX[name]
    out = dict(p)
    out[name] = new
    return out, INSIDE if low <= new <= high else OUTSIDE


def plateau_steps(chosen: Sequence[Mapping], limits: Mapping, *, f=F_SPLIT) -> list[dict]:
    """The 6 G5 steps (lookback, target_vol, crypto_share, each x0.8 then x1.2), each applied to every entry of
    ``chosen`` at once (G5(a): every fold's choice; G5(b): ``[default]``). Every stepped s passes :func:`check_shares`
    (stop rule 12). Each step: ``param``, ``factor``, ``params`` (per entry), ``marks`` and ``mark``."""
    if not chosen:
        raise ValueError("plateau_steps: chosen must hold at least one parameter set")
    steps = []
    for name in PARAM_NAMES:
        for factor in T.PLATEAU_FACTORS:
            pairs = [plateau_step(p, name, factor) for p in chosen]
            for params, _ in pairs:
                check_shares(params["crypto_share"], limits, f=f)
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


# ------------------------------------------------------------------------------------------------ verdict and headline


def verdict(criteria: Mapping, *, stopped: bool = False, changes: int | None = None) -> dict:
    """``trend.verdict`` (TP 12's order) with P read as share changes: "NO EDGE (LOW POWER: k share changes)"."""
    out = T.verdict(criteria, stopped=stopped, switches=changes)
    if out["label"] != out["verdict"]:
        out["label"] = f"{out['verdict']} (LOW POWER: {changes} share changes)"
    return out


def measurement_points(allowed: Sequence[float] = ALLOWED_S) -> list[tuple[str, str]]:
    """Every (item, point) of TP 10's table "Where each gate and R1 is measured (Branch R)", with vol-steady's
    parameter names in the G5 steps, in its order."""
    grid = [f"grid s={T._s(s)}" for s in allowed]
    sk = [f"S({T._s(s)})" for s in allowed]
    points: list[tuple[str, str]] = []
    points += [("G1", p) for p in ["S", *grid, *sk]]
    points += [("G2", f"{p} at 2x") for p in ["S", *grid, *sk]]
    points += [("G3", "S (all rows)"), ("G3", "S (active rows)")]
    points += [("G4", "search studies (all rows)"), ("G4", "search studies (active rows)")]
    steps = [f"{name} x{factor:g}" for name in PARAM_NAMES for factor in T.PLATEAU_FACTORS]
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
    """TP 12's headline over :func:`measurement_points`: the verdict's label unless EDGE; with EDGE, CANDIDATE FOR
    AUDIT only if every point is True in ``results`` (keyed by (item, point)), else EDGE, NOT A CANDIDATE with every
    failing or MISSING point named. Keys that are not measurement points never move it."""
    if verdict_result["verdict"] != EDGE:
        return {"headline": verdict_result["label"], "failing": []}
    failing = [
        f"{item} at {point}"
        for item, point in measurement_points(allowed)
        if results.get((item, point)) is not True
    ]
    return {"headline": T.EDGE_NOT_CANDIDATE if failing else T.CANDIDATE, "failing": failing}


def _rank(value: str, order: Sequence[str]) -> int:
    hits = [i for i, base in enumerate(order) if value == base or value.startswith(base + " (")]
    if not hits:
        raise ValueError(f"unknown outcome {value!r}; expected one of {tuple(order)}")
    return max(hits)


def reported_verdict(previous: Mapping, amendment: Mapping, trigger: str) -> dict:
    """Stop rule 18 (TP 15) with no stop-loss variant: each run has ``verdict``, ``headline``, ``e1_rank_p`` and
    ``e2_p``. Triggers (a), (b) and (c) supersede; "other, after the verdict" reports the less favourable verdict and
    headline of the two (ties to the amendment run's). Any other trigger, None included, is refused."""
    if trigger not in TRIGGERS:
        raise ValueError(f"an amendment run must record its trigger, one of {TRIGGERS}; got {trigger!r}")
    runs = [{"e1_rank_p": r["e1_rank_p"], "e2_p": r["e2_p"]} for r in (previous, amendment)]
    if trigger != TRIGGERS[-1]:
        return {
            "verdict": amendment["verdict"],
            "headline": amendment["headline"],
            "superseded": True,
            "runs": runs,
        }

    def worse(key: str, order: Sequence[str]) -> str:
        a, b = previous[key], amendment[key]
        return a if _rank(a, order) < _rank(b, order) else b

    return {
        "verdict": worse("verdict", T.VERDICT_ORDER),
        "headline": worse("headline", T.HEADLINE_ORDER),
        "superseded": False,
        "runs": runs,
    }


# ------------------------------------------------------------------------------------------------ projection


def project_cpu_minutes(timings: Mapping[str, float], counts: Mapping[str, int]) -> float:
    """Stop rule 17's projection: the sum over :data:`TIMING_KEYS` of seconds per unit x units, in minutes."""
    if set(timings) != set(TIMING_KEYS) or set(counts) != set(TIMING_KEYS):
        raise ValueError(f"project_cpu_minutes: timings and counts must have exactly the keys {TIMING_KEYS}")
    total = 0.0
    for key in TIMING_KEYS:
        total += _real(timings[key], f"timing {key}", 0.0, low_inclusive=True) * _count(counts[key], key, 0)
    return total / 60.0
