"""Dip events, dip features, labels, entry schedules and event-level validation: the dip-timing study.

The study is pre-registered in ``research/dip-timing/PLAN.md`` ("option C"): is a dip worth buying, and when to
buy it. This module holds every computation the study's numbers depend on, tested in ``tests/test_dips.py``
(tamper-the-future, labels by hand on hand-built paths, the event purge, the test-window guard). The study
scripts in ``research/dip-timing/`` only orchestrate.

Vocabulary. Bar positions are integer positions in the daily ``bars`` given (0 = first bar); bars are indexed
by CLOSE time (TESTING.md 4a.5).

- **Trigger** at close t: ``close[t] / max(close[t-N..t]) - 1 <= -X`` (needs a full window, t >= N): the rule of
  ``lab.runner.reference.dip_buy``. ``P_ref`` is that trailing high and ``ref_bar`` the bar that set it (the
  latest one if closes tie).
- **Event**: a trigger at least ``H + 1`` bars after the previous event's trigger. De-duplication runs over every
  trigger from the first bar given, including events that are then dropped. An event is kept when its trigger is
  at or after ``first_bar`` (every feature exists) and its whole span ``[t0, t0 + H + 1]`` lies inside the bars
  given; ``t0 + H + 1`` is the bar whose open fills the exit. Windows count bars; gaps are not filled.
- **Entry plan** of one event: ``((offset, weight), ...)`` with ``0 <= offset < K`` and rising weights: at the
  close of ``t0 + offset`` the target weight becomes ``weight`` (filled at the next open). ``()`` skips the event.
- **Event targets**: the target weight decided at each close ``t0 .. t0 + H``. The plan, overridden by a stop (a
  close ``<= average fill price * (1 - stop)`` from the first fill bar on sets 0, and the event is over: no
  re-entry) and by the exit (0 at the close of ``t0 + H``, filled at the open of ``t0 + H + 1``). The average
  fill price is the mean of the fill opens weighted by each step's weight increase, and it only uses opens of
  bars already filled, so the targets at close d depend on bars up to d only.

Everything a feature or a decision at close t uses is known at that close; labels (``y_`` names) look forward and
never enter features. Model thresholds fire at ``p >= theta - THRESHOLD_ATOL`` (a constant model that predicts
exactly its training base rate fires, whatever the last-bit rounding).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from lab.config import in_window, splits
from lab.data.external import HoldoutWindowError, holdout_cut
from lab.models.features import FEATURES, WARMUP, compute_features, log_array
from lab.runner.interface import validate_bars
from lab.runner.reference import Costs, scheduled
from lab.validation.splits import cpcv, cpcv_paths

__all__ = [
    "B_FEATURES",
    "DAY_COLUMNS",
    "EVENT_COLUMNS",
    "Q_FEATURES",
    "THRESHOLD_ATOL",
    "DipClassifier",
    "DipSpec",
    "bottom_label",
    "check_before_holdout",
    "day_rows",
    "dip_trigger",
    "event_cpcv",
    "event_features",
    "event_paths",
    "event_targets",
    "find_events",
    "fires",
    "first_signal_plan",
    "holm",
    "ladder_plan",
    "load_study_bars",
    "load_study_positioning",
    "month_bootstrap",
    "narrow_range",
    "positioning_features",
    "range_ratio",
    "run_event",
    "schedule_column",
    "trigger_months",
    "up_day",
    "window_events",
]

THRESHOLD_ATOL = 1e-9
DEPTH_HORIZON = 20  # depth below P_ref is in units of ewma_vol_20 * sqrt(20): a 20-bar move
RANGE_LOOKBACK = 5  # T4: today's log range against the mean of the previous 5
Q_FEATURES: tuple[str, ...] = ("q_speed", "q_ma_dist_100", "q_vol_ratio_10_60")
B_FEATURES: tuple[str, ...] = ("b_days", "b_depth", "b_bounce", "b_range_ratio", "b_up_day", "b_volume_z")
EVENT_COLUMNS: tuple[str, ...] = ("t0", "ref_bar", "end_bar", "p_ref", "ts0", "ts_ref", "ts_end")
DAY_COLUMNS: tuple[str, ...] = ("event", "offset", "d", *B_FEATURES, *FEATURES, *Q_FEATURES)


def _int(name: str, value, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer) or value < minimum:
        raise ValueError(f"{name} must be an int >= {minimum}, got {value!r}")
    return int(value)


def _fraction(name: str, value, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 < float(value) < 1.0:
        raise ValueError(f"{name} must be a fraction in (0, 1), got {value!r}")
    return float(value)


@dataclass(frozen=True)
class DipSpec:
    """One dip definition and its shared exit (PLAN.md sections 2-4); the defaults are D0.

    - ``drop`` (X) and ``lookback`` (N): the trigger.
    - ``hold`` (H): the exit is decided at the close of ``t0 + H`` and filled at the open of ``t0 + H + 1``;
      the cool-off between triggers is ``H + 1`` bars.
    - ``entry_window`` (K): entries are decided at the closes ``t0 .. t0 + K - 1``.
    - ``stop``: fraction below the average fill price (None: no stop).
    - ``first_bar``: the first bar an event may trigger on (every feature exists from ``WARMUP - 1``).
    - ``ladder``: T2's extra drops below the trigger level, one tranche each (plus the first at t0).
    - ``bounce_tol``, ``bounce_horizon``: y_B(d) = 1 when no low of the next ``bounce_horizon`` bars is more
      than ``bounce_tol`` below close[d].
    """

    drop: float = 0.15
    lookback: int = 20
    hold: int = 30
    entry_window: int = 10
    stop: float | None = 0.15
    first_bar: int = WARMUP - 1
    ladder: tuple[float, ...] = (0.05, 0.10)
    bounce_tol: float = 0.05
    bounce_horizon: int = 10

    def __post_init__(self) -> None:
        _fraction("drop", self.drop)
        _int("lookback", self.lookback, 1)
        _int("hold", self.hold, 1)
        _int("entry_window", self.entry_window, 1)
        _fraction("stop", self.stop, allow_none=True)
        _int("first_bar", self.first_bar, 0)
        _fraction("bounce_tol", self.bounce_tol)
        _int("bounce_horizon", self.bounce_horizon, 1)
        if self.entry_window > self.hold:
            raise ValueError(f"entry_window ({self.entry_window}) must be <= hold ({self.hold})")
        if self.entry_window - 1 + self.bounce_horizon > self.span:
            raise ValueError("the y_B window of the last entry day must stay inside the event span")
        if not self.ladder or any(_fraction("ladder step", s) <= 0 for s in self.ladder):
            raise ValueError(f"ladder must be a non-empty tuple of fractions, got {self.ladder!r}")
        if list(self.ladder) != sorted(set(self.ladder)):
            raise ValueError(f"ladder steps must be strictly increasing, got {self.ladder!r}")

    @property
    def span(self) -> int:
        """Bars from the trigger to the exit fill: the event covers bars ``t0 .. t0 + span``."""
        return self.hold + 1


# ------------------------------------------------------------------------------------------------- events


def dip_trigger(close: np.ndarray, drop: float, lookback: int) -> np.ndarray:
    """True at bar t when ``close[t] / max(close[t-lookback..t]) - 1 <= -drop``; False before a full window."""
    close = np.asarray(close, dtype=float)
    signal = np.zeros(len(close), dtype=bool)
    if len(close) > lookback:
        peak = sliding_window_view(close, lookback + 1).max(axis=1)
        signal[lookback:] = close[lookback:] / peak - 1.0 <= -drop
    return signal


def find_events(bars: pd.DataFrame, spec: DipSpec = DipSpec()) -> pd.DataFrame:  # noqa: B008 (frozen)
    """The dip events in ``bars`` (module docstring), one row each, columns ``EVENT_COLUMNS``:
    ``t0``, ``ref_bar``, ``end_bar = t0 + span`` (positions), ``p_ref`` and the close times ``ts0``, ``ts_ref``,
    ``ts_end`` of those bars. Rows are in trigger order with a 0-based index."""
    validate_bars(bars)
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    rows = []
    next_free = 0
    for t in np.flatnonzero(dip_trigger(close, spec.drop, spec.lookback)).tolist():
        if t < next_free:
            continue
        next_free = t + spec.hold + 1
        if t < spec.first_bar or t + spec.span > n - 1:
            continue
        window = close[t - spec.lookback : t + 1]
        ref = t - int(np.argmax(window[::-1]))  # the latest bar holding the trailing high
        rows.append((t, ref, t + spec.span, float(close[ref])))
    pos = np.array([r[:3] for r in rows], dtype=np.int64).reshape(-1, 3)
    out = pd.DataFrame(
        {
            "t0": pos[:, 0],
            "ref_bar": pos[:, 1],
            "end_bar": pos[:, 2],
            "p_ref": np.array([r[3] for r in rows], dtype=float),
            "ts0": bars.index[pos[:, 0]],
            "ts_ref": bars.index[pos[:, 1]],
            "ts_end": bars.index[pos[:, 2]],
        }
    )
    return out


def window_events(events: pd.DataFrame, window: tuple[pd.Timestamp, pd.Timestamp | None]) -> np.ndarray:
    """Mask of the events whose whole span ``[ts0, ts_end]`` lies in ``window`` (a value of ``config.splits``)."""
    start = in_window(pd.DatetimeIndex(events["ts0"]), window)
    end = in_window(pd.DatetimeIndex(events["ts_end"]), window)
    return start & end


def trigger_months(events: pd.DataFrame) -> np.ndarray:
    """``"YYYY-MM"`` of each event's trigger DAY (the daily bar closing at ts0 covers the day before ts0)."""
    day = pd.DatetimeIndex(events["ts0"]) - pd.Timedelta(days=1)
    return np.asarray(day.strftime("%Y-%m"), dtype=object)


# ----------------------------------------------------------------------------------------------- features


def _features_for(bars: pd.DataFrame, features: pd.DataFrame | None) -> pd.DataFrame:
    if features is None:
        return compute_features(bars)
    if not features.index.equals(bars.index) or list(features.columns) != list(FEATURES):
        raise ValueError("features must be compute_features(bars) for these bars")
    return features


def _log_range(bars: pd.DataFrame) -> np.ndarray:
    return log_array(bars["high"].to_numpy(dtype=float) / bars["low"].to_numpy(dtype=float))


def range_ratio(bars: pd.DataFrame) -> np.ndarray:
    """``ln(high/low)[t]`` divided by its mean over ``t-5 .. t-1``; NaN for t < 5. Where that mean is 0 (five
    bars with high == low) the ratio is 1.0 for a flat bar and +inf for any range."""
    validate_bars(bars)
    rng = _log_range(bars)
    out = np.full(len(rng), np.nan)
    if len(rng) > RANGE_LOOKBACK:
        prev = sliding_window_view(rng[:-1], RANGE_LOOKBACK).mean(axis=1)
        now = rng[RANGE_LOOKBACK:]
        flat = prev <= 0.0
        out[RANGE_LOOKBACK:] = np.where(
            flat, np.where(now > 0.0, np.inf, 1.0), now / np.where(flat, 1.0, prev)
        )
    return out


def narrow_range(bars: pd.DataFrame) -> np.ndarray:
    """T4's signal: ``ln(high/low)[t] <`` its mean over ``t-5 .. t-1`` (False for t < 5)."""
    ratio = range_ratio(bars)
    return np.where(np.isnan(ratio), False, ratio < 1.0)


def up_day(bars: pd.DataFrame) -> np.ndarray:
    """T3's signal: ``close[t] > high[t-1]`` (False at t = 0)."""
    validate_bars(bars)
    close = bars["close"].to_numpy(dtype=float)
    high = bars["high"].to_numpy(dtype=float)
    out = np.zeros(len(close), dtype=bool)
    out[1:] = close[1:] > high[:-1]
    return out


def event_features(
    bars: pd.DataFrame, events: pd.DataFrame, spec: DipSpec, features: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Dip-quality features at each trigger close (``Q_FEATURES``) plus ``ewma_vol_20`` there (the input of the
    volatility-only baseline). ``q_speed`` = bars from ``P_ref`` to t0 divided by N."""
    feats = _features_for(bars, features)
    t0 = events["t0"].to_numpy(dtype=np.int64)
    out = pd.DataFrame(index=events.index)
    out["q_speed"] = (t0 - events["ref_bar"].to_numpy(dtype=np.int64)) / spec.lookback
    out["q_ma_dist_100"] = feats["ma_dist_100"].to_numpy()[t0]
    out["q_vol_ratio_10_60"] = feats["vol_ratio_10_60"].to_numpy()[t0]
    out["ewma_vol_20"] = feats["ewma_vol_20"].to_numpy()[t0]
    return out


def day_rows(
    bars: pd.DataFrame, events: pd.DataFrame, spec: DipSpec, features: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per event and entry day ``d = t0 + offset`` (``offset = 0 .. K-1``), columns ``DAY_COLUMNS``:
    ``event`` (the events index label), ``offset``, ``d``; the bottom-in features at close d (``B_FEATURES``):

    - ``b_days``: offset (days since the trigger);
    - ``b_depth``: ``ln(close[d] / P_ref) / (ewma_vol_20[d] * sqrt(20))`` (<= 0 while below the trailing high);
    - ``b_bounce``: ``ln(close[d] / min(low[t0..d]))``;
    - ``b_range_ratio``: :func:`range_ratio`; ``b_up_day``: :func:`up_day` as 0/1; ``b_volume_z``: volume_z_20;

    then the 15 ``FEATURES`` at close d and the event's ``Q_FEATURES`` (known at t0 <= d).
    """
    feats = _features_for(bars, features)
    q = event_features(bars, events, spec, feats)
    close = bars["close"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    ratio, upd = range_ratio(bars), up_day(bars)
    ewma = feats["ewma_vol_20"].to_numpy()
    fmat = feats.to_numpy()
    k = spec.entry_window
    parts = []
    for label, t0, p_ref in zip(events.index, events["t0"], events["p_ref"], strict=True):
        d = np.arange(t0, t0 + k)
        lows = np.minimum.accumulate(low[t0 : t0 + k])
        if not (ewma[d] > 0).all():
            raise ValueError(f"ewma_vol_20 is not positive on the entry days of the event at bar {t0}")
        block = pd.DataFrame(
            {
                "event": label,
                "offset": np.arange(k),
                "d": d,
                "b_days": np.arange(k, dtype=float),
                "b_depth": log_array(close[d] / p_ref) / (ewma[d] * math.sqrt(DEPTH_HORIZON)),
                "b_bounce": log_array(close[d] / lows),
                "b_range_ratio": ratio[d],
                "b_up_day": upd[d].astype(float),
                "b_volume_z": feats["volume_z_20"].to_numpy()[d],
            }
        )
        block[list(FEATURES)] = fmat[d]
        for name in Q_FEATURES:
            block[name] = q.at[label, name]
        parts.append(block)
    if not parts:
        return pd.DataFrame({c: pd.Series(dtype=float) for c in DAY_COLUMNS})
    return pd.concat(parts, ignore_index=True)[list(DAY_COLUMNS)]


def bottom_label(bars: pd.DataFrame, d, spec: DipSpec) -> np.ndarray:
    """``y_B(d)``: 1.0 if ``min(low[d+1 .. d+h]) >= close[d] * (1 - tol)`` (h, tol = ``spec.bounce_horizon``,
    ``spec.bounce_tol``), else 0.0; NaN where the window runs past the last bar. A label, never a feature."""
    validate_bars(bars)
    close = bars["close"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    d = np.asarray(d, dtype=np.int64)
    h = spec.bounce_horizon
    out = np.full(len(d), np.nan)
    ok = d + h <= len(close) - 1
    if len(close) > h:
        future_min = sliding_window_view(low[1:], h).min(axis=1)  # [i] = min(low[i+1 .. i+h])
        out[ok] = (future_min[d[ok]] >= close[d[ok]] * (1.0 - spec.bounce_tol)).astype(float)
    return out


def positioning_features(
    bars: pd.DataFrame, events: pd.DataFrame, positioning: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """``(funding_7d per bar, oi_chg_dip per event)`` from :func:`lab.data.external.load_positioning` rows.

    - ``funding_7d[t]``: ``funding_mean_7d`` at close t (the mean of the 21 eight-hour funding rates known
      strictly before the close; NaN unless the 7 days are covered);
    - ``oi_chg_dip``: ``ln(oi_last at close t0 / oi_last at the close of ref_bar)``, NaN where either is missing.
      ``oi_last`` is the newest open interest known strictly before the close (``known_at < close``).
    """
    pos = positioning.reindex(bars.index)
    funding = pos["funding_mean_7d"].to_numpy(dtype=float)
    oi = pos["oi_last"].to_numpy(dtype=float)
    t0 = events["t0"].to_numpy(dtype=np.int64)
    ref = events["ref_bar"].to_numpy(dtype=np.int64)
    ok = np.isfinite(oi[t0]) & np.isfinite(oi[ref]) & (oi[t0] > 0) & (oi[ref] > 0)
    chg = np.full(len(t0), np.nan)
    chg[ok] = log_array(oi[t0][ok] / oi[ref][ok])
    return funding, chg


# ------------------------------------------------------------------------------------------ entry plans


def fires(p, theta: float) -> np.ndarray:
    """``p >= theta - THRESHOLD_ATOL`` elementwise."""
    return np.asarray(p, dtype=float) >= theta - THRESHOLD_ATOL


def first_signal_plan(signal: Sequence[bool]) -> tuple[tuple[tuple[int, float], ...], bool]:
    """``(plan, forced)`` for a pure timing rule: full weight at the first offset whose ``signal`` is True, or at
    the last offset (a forced entry, ``forced=True``) when it never is. ``signal`` has one value per entry day."""
    sig = np.asarray(signal, dtype=bool)
    if sig.ndim != 1 or len(sig) == 0:
        raise ValueError("signal needs one value per entry day")
    hits = np.flatnonzero(sig)
    if len(hits):
        return ((int(hits[0]), 1.0),), False
    return ((len(sig) - 1, 1.0),), True


def ladder_plan(close: np.ndarray, t0: int, p_ref: float, spec: DipSpec) -> tuple[tuple[int, float], ...]:
    """T2: target weight ``k / (len(ladder) + 1)`` where k - 1 is the number of ladder levels
    ``P_ref * (1 - X - step)`` that some close in ``t0 .. d`` has reached (``<=``). The first tranche is decided
    at t0; a level first reached at close d adds its tranche at d (several on one day add together). Levels not
    reached by ``t0 + K - 1`` are never bought."""
    levels = [p_ref * (1.0 - spec.drop - step) for step in spec.ladder]
    steps = len(levels) + 1
    plan: list[tuple[int, float]] = []
    low_so_far = math.inf
    weight = 0.0
    for o in range(spec.entry_window):
        low_so_far = min(low_so_far, float(close[t0 + o]))
        w = float(1 + sum(low_so_far <= level for level in levels)) / steps
        if w > weight:
            plan.append((o, w))
            weight = w
    return tuple(plan)


def _check_plan(plan, spec: DipSpec) -> dict[int, float]:
    last_o, last_w = -1, 0.0
    for o, w in plan:
        ok_offset = isinstance(o, int | np.integer) and not isinstance(o, bool)
        if not (ok_offset and last_o < o < spec.entry_window and last_w < w <= 1.0):
            raise ValueError(f"bad entry plan {plan!r}: offsets in [0, {spec.entry_window}) and weights rising in (0, 1]")
        last_o, last_w = int(o), float(w)
    return {int(o): float(w) for o, w in plan}


def event_targets(bars: pd.DataFrame, t0: int, plan, spec: DipSpec) -> tuple[np.ndarray, dict]:
    """Target weights decided at the closes ``t0 .. t0 + H`` (length H + 1) for one event and entry plan, and
    a summary: ``entered``, ``fill_bars`` (bars whose open fills a buy), ``avg_fill`` (NaN if never filled),
    ``stop_bar`` (close that triggered the stop, or None), ``exit_bar`` (bar whose open fills the exit, None if
    never entered), ``final_weight`` (largest weight held). See the module docstring for the rules."""
    steps = _check_plan(plan, spec)
    o_ = bars["open"].to_numpy(dtype=float)
    c_ = bars["close"].to_numpy(dtype=float)
    if t0 < 0 or t0 + spec.span > len(c_) - 1:
        raise ValueError(f"the event at bar {t0} needs bars up to {t0 + spec.span}; there are {len(c_)}")
    targets = np.zeros(spec.hold + 1)
    weight = 0.0
    paid = filled = 0.0  # sum(open * weight step) and sum(weight step) over fills so far
    pending: tuple[int, float] | None = None
    fill_bars: list[int] = []
    stop_bar = None
    for o in range(spec.hold + 1):
        d = t0 + o
        if pending is not None:  # the step decided at close d-1 filled at the open of d
            paid += o_[pending[0]] * pending[1]
            filled += pending[1]
            fill_bars.append(pending[0])
            pending = None
        new = weight
        if stop_bar is not None or o == spec.hold:
            new = 0.0
        elif filled > 0 and spec.stop is not None and c_[d] <= paid / filled * (1.0 - spec.stop):
            new, stop_bar = 0.0, d
        elif o in steps and steps[o] > weight:
            new = steps[o]
            pending = (d + 1, new - weight)
        targets[o] = new
        weight = new
    entered = filled > 0
    max_weight = float(targets.max())
    info = {
        "entered": entered,
        "fill_bars": fill_bars,
        "avg_fill": paid / filled if entered else math.nan,
        "stop_bar": stop_bar,
        "exit_bar": (stop_bar + 1 if stop_bar is not None else t0 + spec.span) if entered else None,
        "final_weight": max_weight,
    }
    return targets, info


def schedule_column(n: int, events: pd.DataFrame, targets: Mapping[int, np.ndarray]) -> np.ndarray:
    """A ``scheduled`` column over ``n`` bars: 0 everywhere except each event's targets at its closes
    ``t0 .. t0 + H``. ``targets`` maps an events index label to its targets; events not in it are skipped
    (stay 0). Events whose decision bars overlap raise ``ValueError``."""
    col = np.zeros(n)
    used = np.zeros(n, dtype=bool)
    for label, t in targets.items():
        t0 = int(events.at[label, "t0"])
        t = np.asarray(t, dtype=float)
        if t0 + len(t) > n:
            raise ValueError(f"event {label!r} runs past the {n} bars")
        if used[t0 : t0 + len(t)].any():
            raise ValueError(f"event {label!r} overlaps another event's decision bars")
        used[t0 : t0 + len(t)] = True
        col[t0 : t0 + len(t)] = t
    return col


def run_event(bars: pd.DataFrame, t0: int, plan, spec: DipSpec, costs: Costs) -> dict:
    """One event on a fresh sleeve (``costs.capital_usd``, cash before and after), through the reference engine
    (``scheduled``) on bars ``t0 .. t0 + span``. Returns the :func:`event_targets` summary plus ``r`` (net return of
    the sleeve over the event after all costs, 0.0 for a skipped event), ``n_fills``, ``distance`` (average fill
    price over the lowest low of ``t0 .. t0 + H``, minus 1) and ``mae`` (lowest low from the first fill bar to the
    bar before the exit, or the exit open if lower, over the average fill price, minus 1). SCOUTING ONLY: the
    reference engine, not NautilusTrader (AGENTS.md hard rule 3)."""
    targets, info = event_targets(bars, t0, plan, spec)
    piece = bars.iloc[t0 : t0 + spec.span + 1][["open", "high", "low", "close", "volume"]]
    col = np.zeros(len(piece))
    col[: spec.hold + 1] = targets
    res = scheduled({"col": "target"}, piece.assign(target=col), costs)
    filled_at = (t0 + np.flatnonzero(res["turnover"].to_numpy() > 0)).tolist()
    expected = info["fill_bars"] + ([info["exit_bar"]] if info["entered"] else [])
    assert filled_at == expected, f"engine fills {filled_at} differ from the schedule's {expected}"
    low = bars["low"].to_numpy(dtype=float)
    out = dict(info)
    out["r"] = float(np.prod(1.0 + res["ret"].to_numpy()) - 1.0)
    out["n_fills"] = len(filled_at)
    out["distance"] = math.nan
    out["mae"] = math.nan
    if info["entered"]:
        avg = info["avg_fill"]
        out["distance"] = avg / float(low[t0 : t0 + spec.hold + 1].min()) - 1.0
        first, exit_bar = info["fill_bars"][0], info["exit_bar"]
        worst = min(float(low[first:exit_bar].min()), float(bars["open"].iloc[exit_bar]))
        out["mae"] = worst / avg - 1.0
    return out


# ------------------------------------------------------------------------------------------------ models


class DipClassifier:
    """The study's classifiers. ``kind``:

    - ``"logistic"``: L2 logistic regression, C = 1, on inputs standardised with the TRAINING rows' mean and
      standard deviation (a constant column is centred only);
    - ``"lightgbm"``: ``lab.models.train.make_model("classification", seed)`` (small, heavily regularised).

    If the training labels hold one class only, the model predicts that class's share (0.0 or 1.0) for every
    row. ``predict`` returns P(y = 1).
    """

    def __init__(self, kind: str, seed: int = 0):
        if kind not in ("logistic", "lightgbm"):
            raise ValueError(f"kind must be 'logistic' or 'lightgbm', got {kind!r}")
        self.kind, self.seed = kind, seed
        self.columns: list[str] = []
        self.constant: float | None = None
        self.model = None

    def fit(self, X: pd.DataFrame, y) -> DipClassifier:
        y = np.asarray(y, dtype=float)
        x = X.to_numpy(dtype=float)
        if len(y) != len(x) or len(y) == 0 or not np.isfinite(x).all() or not np.isin(y, (0.0, 1.0)).all():
            raise ValueError("fit needs finite features and 0/1 labels, one per row")
        self.columns = list(X.columns)
        classes = np.unique(y)
        if len(classes) == 1:
            self.constant = float(classes[0])
            return self
        self.constant = None
        if self.kind == "logistic":
            from sklearn.linear_model import LogisticRegression

            self.mean = x.mean(axis=0)
            sd = x.std(axis=0)
            self.sd = np.where(sd > 0, sd, 1.0)
            self.model = LogisticRegression(C=1.0, max_iter=1000).fit((x - self.mean) / self.sd, y)
        else:
            from lab.models.train import make_model

            self.model = make_model("classification", self.seed).fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if list(X.columns) != self.columns:
            raise ValueError(f"predict needs the columns {self.columns}, got {list(X.columns)}")
        if self.constant is not None:
            return np.full(len(X), self.constant)
        if self.kind == "logistic":
            return self.model.predict_proba((X.to_numpy(dtype=float) - self.mean) / self.sd)[:, 1]
        return self.model.predict_proba(X)[:, 1]


# ------------------------------------------------------------------------------------ event-level CPCV


def event_cpcv(
    ts0, ts_end, n_groups: int = 6, n_test_groups: int = 2, embargo: pd.Timedelta = pd.Timedelta(days=31)  # noqa: B008
) -> list[tuple[np.ndarray, np.ndarray, tuple[int, ...]]]:
    """CPCV over events sorted by trigger time: ``splits.cpcv`` groups (contiguous, in trigger order), then

    - purge: drop a training event whose span ``[ts0, ts_end]`` overlaps a test group's span (the first trigger
      to the last exit of that group);
    - embargo: drop a training event that triggers within ``embargo`` after a test group's span ends.

    Returns ``[(train_idx, test_idx, test_groups), ...]`` like ``splits.cpcv``. Raises ``ValueError`` if the
    events are not sorted by ``ts0``, a span ends before it starts, or a split keeps no training event.
    """
    start = pd.DatetimeIndex(ts0)
    end = pd.DatetimeIndex(ts_end)
    if len(start) != len(end) or not start.is_monotonic_increasing:
        raise ValueError("events must be sorted by ts0, with one ts_end each")
    if (end < start).any():
        raise ValueError("an event's span ends before it starts")
    if embargo < pd.Timedelta(0):
        raise ValueError(f"embargo must be >= 0, got {embargo}")
    groups = np.array_split(np.arange(len(start)), n_groups)
    out = []
    for train_idx, test_idx, test_groups in cpcv(len(start), n_groups, n_test_groups):
        keep = np.ones(len(train_idx), dtype=bool)
        for g in test_groups:
            lo, hi = start[groups[g]].min(), end[groups[g]].max()
            overlap = (start[train_idx] <= hi) & (end[train_idx] >= lo)
            embargoed = (start[train_idx] > hi) & (start[train_idx] <= hi + embargo)
            keep &= ~(overlap | embargoed)
        if not keep.any():
            raise ValueError(f"purge and embargo leave no training event for test groups {test_groups}")
        out.append((train_idx[keep], test_idx, test_groups))
    return out


def event_paths(n: int, n_groups: int, n_test_groups: int, split_values) -> np.ndarray:
    """``splits.cpcv_paths`` for event-level values: ``(n_paths, n)``, each event once per path, taken from the
    j-th split that tested it."""
    return cpcv_paths(n, n_groups, n_test_groups, split_values)


# ---------------------------------------------------------------------------------------------- inference


def month_bootstrap(delta, months, n_draws: int = 10_000, seed: int = 0) -> dict:
    """One-sided bootstrap test of ``mean(delta) > 0`` that resamples whole trigger months (events of one month,
    BTC and ETH together, stay together; the number of months drawn equals the number observed).

    p = (1 + #{mean* - mean >= mean}) / (n_draws + 1), the shifted (null-centred) bootstrap. Keys: ``mean``,
    ``p``, ``ci_low``, ``ci_high`` (2.5% and 97.5% of the bootstrap means), ``n_events``, ``n_months``.
    """
    delta = np.asarray(delta, dtype=float)
    months = np.asarray(months)
    if delta.ndim != 1 or len(delta) == 0 or len(months) != len(delta) or not np.isfinite(delta).all():
        raise ValueError("delta must be a non-empty 1-D finite array with one month per value")
    _int("n_draws", n_draws, 1)
    uniq, inv = np.unique(months, return_inverse=True)
    sums = np.bincount(inv, weights=delta, minlength=len(uniq))
    counts = np.bincount(inv, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(uniq), size=(n_draws, len(uniq)))
    boot = sums[draw].sum(axis=1) / counts[draw].sum(axis=1)
    mean = float(delta.mean())
    return {
        "mean": mean,
        "p": float((1 + np.sum(boot - mean >= mean)) / (n_draws + 1)),
        "ci_low": float(np.quantile(boot, 0.025)),
        "ci_high": float(np.quantile(boot, 0.975)),
        "n_events": len(delta),
        "n_months": len(uniq),
    }


def holm(pvalues) -> np.ndarray:
    """Holm step-down adjusted p-values (same order as given; monotone; capped at 1)."""
    p = np.asarray(pvalues, dtype=float)
    if p.ndim != 1 or not ((p >= 0) & (p <= 1)).all():
        raise ValueError("pvalues must be a 1-D array of probabilities")
    m = len(p)
    order = np.argsort(p, kind="stable")
    adjusted = np.minimum(1.0, np.maximum.accumulate((m - np.arange(m)) * p[order]))
    out = np.empty(m)
    out[order] = adjusted
    return out


# ------------------------------------------------------------------------------------- test-window guard


FIRST_CLOSE = pd.Timestamp("2017-01-02", tz="UTC")  # the first train bar (day 2017-01-01) closes here


def check_before_holdout(index: pd.DatetimeIndex, config_dir: Path | None = None) -> None:
    """Raise :class:`HoldoutWindowError` if anything in ``index`` closes after the last validate bar
    (``external.holdout_cut``: 2024-07-01 00:00 UTC). The study never reads the test window."""
    cut = holdout_cut(config_dir)
    if len(index) and pd.DatetimeIndex(index).max() > cut:
        raise HoldoutWindowError(f"data reach {pd.DatetimeIndex(index).max().isoformat()}, after {cut.isoformat()}")


def _last_close(last_close, config_dir: Path | None) -> pd.Timestamp:
    cut = holdout_cut(config_dir)
    ts = pd.Timestamp(last_close)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts > cut:
        raise HoldoutWindowError(f"last_close {ts.isoformat()} is after {cut.isoformat()} (the test window)")
    return ts


def load_study_bars(
    instrument: str,
    last_close,
    catalog_dir: str | Path = "data/catalog",
    config_dir: Path | None = None,
    loader: Callable | None = None,
) -> pd.DataFrame:
    """Daily bars of ``instrument`` from the first train close (2017-01-02) to ``last_close`` (at most the last
    validate close), restricted to the train and validate windows; raises :class:`HoldoutWindowError` if the
    request or anything returned reaches the test window. ``loader`` defaults to ``lab.data.catalog.load_bars``."""
    end = _last_close(last_close, config_dir)
    if loader is None:
        from lab.data.catalog import load_bars as loader
    bars = loader(instrument, "1d", start=FIRST_CLOSE, end=end, catalog_dir=catalog_dir)
    sp = splits(config_dir)
    keep = in_window(bars.index, sp["train"]) | in_window(bars.index, sp["validate"])
    out = bars.loc[keep]
    check_before_holdout(bars.index, config_dir)
    attrs = dict(bars.attrs)
    out.attrs = attrs
    return out


def load_study_positioning(
    symbol: str,
    last_close,
    catalog_dir: str | Path = "data/catalog",
    config_dir: Path | None = None,
    loader: Callable | None = None,
) -> pd.DataFrame:
    """Daily positioning rows of ``symbol`` up to ``last_close`` (``lab.data.external.load_positioning``), with
    the same test-window guard as :func:`load_study_bars`."""
    end = _last_close(last_close, config_dir)
    if loader is None:
        from lab.data.external import load_positioning as loader
    pos = loader(symbol, "1d", end=end, catalog_dir=catalog_dir, config_dir=config_dir)
    check_before_holdout(pos.index, config_dir)
    return pos
