"""rebalance-steady adapter and harness: the code PLAN.md section 14 lists under "Adapter ``lab/runner/steady.py``".

**SCOUTING only** (tests, demos and scouting; never in reports): it drives :mod:`lab.runner.portfolio`, the
reference rebalancer, not NautilusTrader (AGENTS.md hard rule 3). ``research/rebalance-steady/PLAN.md`` is the
contract; section numbers below are that file's. ``lab/search`` and ``lab/validation`` are used as they are.

The strategy (sections 4-5)
---------------------------
Four searched parameters (:data:`SPECS`): ``coin_share`` s, ``btc_share`` f, ``band_rel`` b and ``every``. They map
to :func:`lab.runner.portfolio.rebalance` as w_btc = s*f, w_eth = s*(1 - f), band = b*s, every, with the Steady
limits as :func:`lab.runner.portfolio.risk_limits` read them (never typed) and ``headroom`` :data:`HEADROOM`.
:func:`steady_backtest` is the ``BacktestFn``; bind ``limits`` and ``costs`` with ``functools.partial`` (picklable).

The harness (section 8)
-----------------------
Every slice is defined by CLOSE TIMES taken from the Kraken panel (row numbers only on that panel) and applied with
``.loc`` to each panel. For a fold's test rows ``test`` on the Kraken index K (:func:`fold_window`):
first_h120 = K[max(0, test[0] - warmup)] (``walk_forward_optimize``'s context start), first_h1 = K[test[0] - 1],
t0 = K[test[0]], last = K[test[-1]]. Kept rows are the slice rows closing after t0
(``res["ret"].loc[t0:].iloc[1:]``, as ``walk_forward_optimize`` keeps them). Passing ``like=<Kraken panel>``
asserts that a slice of another panel (Binance) has exactly the Kraken slice's index, else
:class:`SliceMismatchError` (the plan's "stop"). Any slice must start exactly at its first close and end exactly
at its last close, so a panel missing one of those closes is refused too.

- H120 (S, B1, B2, B5): the slice first_h120 .. last.
- H1 (B3, B4): the slice first_h1 .. last. The book buys at the open of t0, outside the kept rows; B3 draws its
  rebalance closes from slice closes 1 .. n-2 = the closes t0 .. last-1, whose orders fill inside the kept rows.
- B3 and B4 start from S's book (:func:`book_value`): V = S's H120 ``costs.capital_usd`` times the product of
  (1 + ret) over S's rows up to and including close first_h1, multiplied in time order (the engine's own book,
  exactly, unless some bar lost more than half the book). Their costs are ``costs`` with ``capital_usd = V``
  (:func:`book_costs`); for 2x pass the 2x costs and V from S at 2x.

Pinned definitions where the plan is loosely worded (handoff open items 2 and 3)
------------------------------------------------------------------------------
- **Report trial Sharpes** (strict DSR, section 12): :func:`report_trial_sharpes`, exactly
  ``overfitting_report``'s list: for each study in the given order, m = ``load_trial_returns(study,
  out_dir).dropna()``; studies with fewer than 2 columns are skipped; then ``stats.sharpe`` (per period) of each
  column in column order.
- **Per-study PBO and its logits** (sections 9-10): :func:`study_pbo`, ``stats.pbo(m.to_numpy(), n_blocks=10)``
  on that same matrix (``None`` when it has fewer than 2 columns, which the report skips too).
- **The stable-region neighbours** (section 7): :func:`stable_neighbours`, the same computation as
  ``lab.search.stability.stable_region`` (completed trials with a finite value, unit space, Euclidean distance,
  ``k = min(10, n)`` nearest by ``np.argsort``, ties to the best own score); it returns the chosen trial's
  neighbours in argsort order.
- **Panel hash** (sections 11-12): :func:`panel_hash`, SHA-256 of the index as little-endian int64 microseconds
  since the epoch (UTC close times), followed by the values as little-endian float64, row-major (row by row,
  columns in the pinned panel order BTC open, high, low, close, volume, ETH open, ..., volume). Hex digest. attrs
  are not hashed.
- **G5 step marks**: per fold "free", "clipped" (the clip moved the stepped value, but not back to the chosen
  value) or "at the limit" (it cannot move: that fold repeats its chosen value). A step's mark is the most
  restrictive of its fold marks: "at the limit" if any fold is, else "clipped" if any fold is, else "free" (so a
  step with one fold at ``every`` = 1 going down is "at the limit", the plan's example). The fold marks are
  returned too. "PASS (weak)" counts steps whose mark is not "free".
- **G8**: profits are ``math.fsum`` of ``np.log1p`` of the returns; a regime "has more than half" when its profit
  > total / 2, so exactly half passes.
"""

from __future__ import annotations

import hashlib
import math
import numbers
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from lab.runner.interface import BacktestFn
from lab.runner.portfolio import (
    asset_bars,
    check_targets,
    random_rebalance,
    rebalance,
    risk_limits,
    validate_panel,
)
from lab.runner.reference import (
    Costs,
    _check_params,
    _param_float,
    _param_int,
    _real,
    buy_and_hold,
    constant_mix,
)
from lab.search.space import Param
from lab.search.study import load_trial_returns
from lab.validation import stats
from lab.validation.montecarlo import percentiles, stationary_bootstrap_indices

__all__ = [
    "B3_DRAWS",
    "BOOTSTRAP_RESAMPLES",
    "HEADROOM",
    "MARKS",
    "MEAN_BLOCK",
    "PARAM_NAMES",
    "PLATEAU_FACTORS",
    "PLATEAU_KEEP",
    "REGIMES",
    "REGIME_THRESHOLD",
    "SPECS",
    "WARMUP",
    "SliceMismatchError",
    "Window",
    "book_costs",
    "book_value",
    "buy_and_hold_b1",
    "check_box",
    "e1_rank",
    "fifty_fifty_b2",
    "fold_window",
    "h1_slice",
    "h120_slice",
    "harness_slice",
    "kept_fills",
    "kept_returns",
    "limit_only_b5",
    "paired_bootstrap",
    "panel_hash",
    "plateau_step",
    "plateau_steps",
    "plateau_verdict",
    "random_b3",
    "rebalance_params",
    "regime_split",
    "regime_table",
    "report_trial_sharpes",
    "run_h120",
    "stable_neighbours",
    "static_b4",
    "static_span_b4",
    "steady_backtest",
    "steady_limits",
    "study_pbo",
    "targets",
]

HEADROOM = 0.02  # A2: every target stays this far inside every Steady limit
WARMUP = 120  # rows before each test block (walk_forward_optimize's default)
PARAM_NAMES = ("coin_share", "btc_share", "band_rel", "every")
SPECS = (
    Param("coin_share", "float", 0.20, 0.77),
    Param("btc_share", "float", 0.25, 0.75),
    Param("band_rel", "float", 0.02, 0.50, log=True),
    Param("every", "int", 1, 90, log=True),
)
B3_DRAWS = 1000
BOOTSTRAP_RESAMPLES = 10_000
MEAN_BLOCK = 20
PLATEAU_FACTORS = (0.8, 1.2)
PLATEAU_KEEP = 0.7
MARKS = ("free", "clipped", "at the limit")
REGIME_THRESHOLD = 0.10
REGIMES = ("bull", "bear", "sideways")
_PARAMS = frozenset(PARAM_NAMES)


class SliceMismatchError(ValueError):
    """A harness slice does not have the closes the Kraken panel says it must have: stop (PLAN.md sections 3, 8)."""


def _count(value, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


# ------------------------------------------------------------------------------------- the strategy


def _parse(params) -> tuple[float, float, float, int]:
    p = _check_params("steady", params, _PARAMS)
    s = _param_float(p, "coin_share", low=0.0, low_inclusive=False, high=1.0, high_inclusive=True)
    f = _param_float(p, "btc_share", low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    b = _param_float(p, "band_rel", low=0.0, low_inclusive=True)
    return s, f, b, _param_int(p, "every")


def _weights(s: float, f: float) -> tuple[float, float]:
    return s * f, s * (1.0 - f)


def _limit_values(limits) -> tuple[float, float]:
    if not isinstance(limits, Mapping) or limits.get("min_cash") is None or limits.get("max_coin") is None:
        raise ValueError(
            "steady: limits must hold min_cash and max_coin as risk_limits('steady') reads them (the Steady level "
            f"sets both), got {limits!r}"
        )
    return limits["min_cash"], limits["max_coin"]


def steady_limits(config_dir: Path | None = None) -> dict:
    """``risk_limits("steady", config_dir)``, refused (``ValueError``) unless it sets both ``min_cash`` and
    ``max_coin``. ``risk_limits`` itself raises unless the coin list is exactly BTC, ETH and USDC."""
    limits = risk_limits("steady", config_dir)
    _limit_values(limits)
    return limits


def targets(params: Mapping) -> tuple[float, float]:
    """(w_btc, w_eth) = (s*f, s*(1 - f)) of steady params (validated as :func:`rebalance_params` does)."""
    s, f, _, _ = _parse(params)
    return _weights(s, f)


def rebalance_params(params: Mapping, limits: Mapping) -> dict:
    """The ``rebalance`` params of steady params (PLAN.md section 5).

    ``params``: exactly ``coin_share`` (in (0, 1]), ``btc_share`` (in [0, 1]), ``band_rel`` (>= 0) and ``every``
    (int >= 1); unknown or missing keys and bad values raise ``ValueError``. ``limits``: the dict
    :func:`steady_limits` / ``risk_limits("steady")`` returned; ``min_cash`` or ``max_coin`` None raises. Returns
    ``{"w_btc": s*f, "w_eth": s*(1 - f), "band": b*s, "every": every, "min_cash", "max_coin", "headroom":
    HEADROOM}``. The box check is :func:`check_box`; ``rebalance`` refuses targets that break the limits.
    """
    s, f, b, every = _parse(params)
    min_cash, max_coin = _limit_values(limits)
    w_btc, w_eth = _weights(s, f)
    return {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "band": b * s,
        "every": every,
        "min_cash": min_cash,
        "max_coin": max_coin,
        "headroom": HEADROOM,
    }


def steady_backtest(params: Mapping, bars: pd.DataFrame, *, limits: Mapping, costs: Costs) -> pd.DataFrame:
    """The ``BacktestFn``: ``rebalance(rebalance_params(params, limits), bars, costs)``, unchanged result.

    ``limits`` and ``costs`` are built once at run start (``costs`` a :class:`Costs`, e.g. ``Costs.from_yaml()``
    or ``Costs.from_yaml().stressed()``; None is refused so no run reads the YAML file per call). Bind them with
    ``functools.partial(steady_backtest, limits=..., costs=...)`` for ``lab/search``.
    """
    if not isinstance(costs, Costs):
        raise ValueError(f"steady_backtest: costs must be a Costs instance built at run start, got {costs!r}")
    return rebalance(rebalance_params(params, limits), bars, costs)


def check_box(specs: Sequence[Param], limits: Mapping) -> list[tuple[float, float]]:
    """The 4-corner check of PLAN.md section 5: every (s, f) corner of the ``coin_share`` x ``btc_share`` box
    passes ``check_targets`` with the limits as read and :data:`HEADROOM`. s and s*max(f, 1 - f) are bilinear in
    (s, f), so their largest values on the box are at its corners. Returns the 4 corners (s, f); raises
    ``ValueError`` naming the first corner that fails (``run_train.py`` then refuses to start)."""
    by_name = {p.name: p for p in specs}
    if "coin_share" not in by_name or "btc_share" not in by_name:
        raise ValueError("check_box: specs must include coin_share and btc_share")
    min_cash, max_coin = _limit_values(limits)
    s_spec, f_spec = by_name["coin_share"], by_name["btc_share"]
    corners = [(float(s), float(f)) for s in (s_spec.low, s_spec.high) for f in (f_spec.low, f_spec.high)]
    for s, f in corners:
        w_btc, w_eth = _weights(s, f)
        try:
            check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM)
        except ValueError as exc:
            raise ValueError(
                f"check_box: the box corner coin_share = {s!r}, btc_share = {f!r} breaks the limits as read: {exc}"
            ) from exc
    return corners


def panel_hash(panel: pd.DataFrame) -> str:
    """SHA-256 (hex) of a panel's index and values in the pinned byte layout (module docstring)."""
    validate_panel(panel)
    digest = hashlib.sha256()
    digest.update(np.asarray(panel.index.as_unit("us").asi8, dtype="<i8").tobytes(order="C"))
    digest.update(np.asarray(panel.to_numpy(dtype=np.float64), dtype="<f8").tobytes(order="C"))
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------- the harness


class Window(NamedTuple):
    """The close times of one fold's harness slices (PLAN.md section 8)."""

    first_h120: pd.Timestamp
    first_h1: pd.Timestamp
    t0: pd.Timestamp
    last: pd.Timestamp


def fold_window(index: pd.DatetimeIndex, test, warmup: int = WARMUP) -> Window:
    """The :class:`Window` of a test block on the Kraken index: ``test`` is the block's rows (``Fold.test``,
    contiguous, at least 2 rows, starting at row >= 1). first_h120 = index[max(0, test[0] - warmup)], first_h1 =
    index[test[0] - 1], t0 = index[test[0]], last = index[test[-1]]. Phase sensitivity uses ``warmup = 120 + j``."""
    warmup = _count(warmup, "warmup", 1)
    rows = np.asarray(test)
    if (
        rows.ndim != 1
        or len(rows) < 2
        or not np.issubdtype(rows.dtype, np.integer)
        or rows[0] < 1
        or rows[-1] >= len(index)
        or not np.array_equal(rows, np.arange(rows[0], rows[-1] + 1))
    ):
        raise ValueError(
            f"fold_window: test must be >= 2 contiguous rows of the {len(index)}-row index starting at row >= 1"
        )
    first, end = int(rows[0]), int(rows[-1])
    return Window(index[max(0, first - warmup)], index[first - 1], index[first], index[end])


def harness_slice(
    panel: pd.DataFrame, start: pd.Timestamp, last: pd.Timestamp, *, like: pd.DataFrame | None = None
) -> pd.DataFrame:
    """``panel.loc[start:last]``. Raises :class:`SliceMismatchError` unless the slice starts exactly at ``start``
    and ends exactly at ``last`` (at least 2 rows) and, with ``like`` (the Kraken panel), unless its index equals
    ``like.loc[start:last].index``: a Binance slice must have exactly the Kraken closes."""
    piece = panel.loc[start:last]
    if len(piece) < 2 or piece.index[0] != start or piece.index[-1] != last:
        raise SliceMismatchError(f"the panel has no slice that starts at {start} and ends at {last}")
    if like is not None and not piece.index.equals(like.loc[start:last].index):
        raise SliceMismatchError(
            f"the slice {start} .. {last} does not have the Kraken panel's closes (stop: PLAN.md section 8)"
        )
    return piece


def h120_slice(panel: pd.DataFrame, window: Window, *, like: pd.DataFrame | None = None) -> pd.DataFrame:
    """The H120 slice first_h120 .. last (:func:`harness_slice`)."""
    return harness_slice(panel, window.first_h120, window.last, like=like)


def h1_slice(panel: pd.DataFrame, window: Window, *, like: pd.DataFrame | None = None) -> pd.DataFrame:
    """The H1 slice first_h1 .. last (:func:`harness_slice`)."""
    return harness_slice(panel, window.first_h1, window.last, like=like)


def kept_returns(result: pd.DataFrame, t0: pd.Timestamp) -> pd.Series:
    """``result["ret"].loc[t0:].iloc[1:]`` with no attrs: the kept rows, exactly as ``walk_forward_optimize``."""
    kept = result["ret"].loc[t0:].iloc[1:].copy()
    kept.attrs = {}
    return kept


def kept_fills(result: pd.DataFrame, t0: pd.Timestamp) -> int:
    """Fill rows (turnover > 0) among the kept rows: ``walk_forward_optimize``'s ``oos_trades`` (k_i for S)."""
    return int((result["turnover"].loc[t0:].iloc[1:] > 0).sum())


def book_value(result: pd.DataFrame, window: Window, costs: Costs) -> float:
    """S's book V at close ``window.first_h1`` in its H120 ``result`` run with ``costs``: ``costs.capital_usd``
    times (1 + ret) of every row up to and including that close, multiplied in time order."""
    if window.first_h1 not in result.index:
        raise ValueError(f"book_value: close {window.first_h1} is not a row of the result")
    value = costs.capital_usd
    for r in result["ret"].loc[: window.first_h1].to_numpy(dtype=float).tolist():
        value *= 1.0 + r
    return value


def book_costs(costs: Costs, book: float) -> Costs:
    """``costs`` with ``capital_usd = book``: equal to ``Costs.from_yaml(capital_usd=V)`` (1x) or
    ``Costs.from_yaml(capital_usd=V2).stressed()`` (2x) when ``costs`` is the run's 1x or 2x model."""
    return replace(costs, capital_usd=book)


def run_h120(
    backtest_fn: BacktestFn,
    params: Mapping,
    panel: pd.DataFrame,
    window: Window,
    *,
    like: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """``backtest_fn(params, h120 slice)``: S (or a plateau or phase variant) in the H120 harness."""
    return backtest_fn(params, h120_slice(panel, window, like=like))


def buy_and_hold_b1(
    panel: pd.DataFrame, window: Window, costs: Costs, *, like: pd.DataFrame | None = None
) -> pd.DataFrame:
    """B1: ``reference.buy_and_hold({"weight": 1.0}, asset_bars(h120 slice, "BTC"), costs)``."""
    return buy_and_hold({"weight": 1.0}, asset_bars(h120_slice(panel, window, like=like), "BTC"), costs)


def fifty_fifty_b2(
    panel: pd.DataFrame, window: Window, costs: Costs, *, like: pd.DataFrame | None = None
) -> pd.DataFrame:
    """B2: ``reference.constant_mix({"weight": 0.5, "every": 30}, asset_bars(h120 slice, "BTC"), costs)``."""
    piece = h120_slice(panel, window, like=like)
    return constant_mix({"weight": 0.5, "every": 30}, asset_bars(piece, "BTC"), costs)


def random_b3(
    panel: pd.DataFrame,
    window: Window,
    params: Mapping,
    k: int,
    costs: Costs,
    book: float,
    fold: int,
    n_draws: int = B3_DRAWS,
    *,
    like: pd.DataFrame | None = None,
) -> dict:
    """B3, the random-rebalance null: draw j = 0 .. n_draws - 1 is ``random_rebalance({"w_btc", "w_eth":
    targets(params), "n_rebalances": k, "seed": 10*j + fold}, h1 slice, book_costs(costs, book))``.

    ``k`` is S's kept fill rows (k_i); ``fold`` in 0..9 (the validate look uses 0: seeds 10*j). Returns
    ``returns`` (float array, n_draws x kept rows; stitch folds with ``np.hstack`` in fold order), ``index`` (the
    kept closes), ``fills`` (kept fill rows per draw), ``seeds`` and ``closes`` (per draw, the decision closes the
    draw rebalanced at, as close times).
    """
    w_btc, w_eth = targets(params)
    k = _count(k, "k", 0)
    fold = _count(fold, "fold", 0)
    if fold > 9:
        raise ValueError(f"fold must be in 0..9 (seeds 10*j + fold), got {fold}")
    n_draws = _count(n_draws, "n_draws", 1)
    piece = h1_slice(panel, window, like=like)
    run_costs = book_costs(costs, book)
    seeds = 10 * np.arange(n_draws, dtype=np.int64) + fold
    rows, fills, closes = [], [], []
    for seed in seeds.tolist():
        res = random_rebalance(
            {"w_btc": w_btc, "w_eth": w_eth, "n_rebalances": k, "seed": seed}, piece, run_costs
        )
        kept = kept_returns(res, window.t0)
        rows.append(kept.to_numpy(dtype=float))
        fills.append(kept_fills(res, window.t0))
        closes.append(piece.index[res.attrs["rebalance_closes"]])
    return {
        "returns": np.vstack(rows),
        "index": kept.index,
        "fills": np.asarray(fills, dtype=np.int64),
        "seeds": seeds,
        "closes": closes,
    }


def static_b4(
    panel: pd.DataFrame,
    window: Window,
    params: Mapping,
    costs: Costs,
    book: float,
    *,
    like: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """B4: ``random_rebalance`` with ``n_rebalances = 0`` (static within the block) on the H1 slice, from S's book.
    Its only fill is at the open of t0, outside the kept rows."""
    w_btc, w_eth = targets(params)
    piece = h1_slice(panel, window, like=like)
    return random_rebalance(
        {"w_btc": w_btc, "w_eth": w_eth, "n_rebalances": 0, "seed": 0}, piece, book_costs(costs, book)
    )


def limit_only_b5(
    panel: pd.DataFrame,
    window: Window,
    params: Mapping,
    limits: Mapping,
    costs: Costs,
    *,
    like: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """B5 (description): ``rebalance`` with the fold's targets, ``band = 1.0`` (never band-triggered), ``every =
    1``, the limits as read and :data:`HEADROOM`, on the H120 slice: it rebalances only on a limit breach."""
    w_btc, w_eth = targets(params)
    min_cash, max_coin = _limit_values(limits)
    rule = {
        "w_btc": w_btc,
        "w_eth": w_eth,
        "band": 1.0,
        "every": 1,
        "min_cash": min_cash,
        "max_coin": max_coin,
        "headroom": HEADROOM,
    }
    return rebalance(rule, h120_slice(panel, window, like=like), costs)


def static_span_b4(
    panel: pd.DataFrame,
    first: Window,
    last: Window,
    params: Mapping,
    costs: Costs,
    book: float,
    keep: pd.DatetimeIndex,
    *,
    like: pd.DataFrame | None = None,
) -> pd.Series:
    """B4-span (description): the targets of ``params`` bought at the open of ``first.t0`` (fold 0) and held,
    never rebalanced, to ``last.last`` (fold 3's last close): ``random_rebalance`` with ``n_rebalances = 0`` on
    the slice ``first.first_h1 .. last.last``. Returns its returns on ``keep`` (S's stitched kept closes, which
    must all close after ``first.t0`` inside the slice), with no attrs."""
    w_btc, w_eth = targets(params)
    piece = harness_slice(panel, first.first_h1, last.last, like=like)
    res = random_rebalance(
        {"w_btc": w_btc, "w_eth": w_eth, "n_rebalances": 0, "seed": 0}, piece, book_costs(costs, book)
    )
    after = res["ret"].loc[first.t0 :].iloc[1:]
    if not pd.DatetimeIndex(keep).isin(after.index).all():
        raise ValueError("static_span_b4: every kept close must be a slice close after first.t0")
    out = after.loc[keep].copy()
    out.attrs = {}
    return out


# --------------------------------------------------------------------------------------- G5, plateau


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _feasible(name: str, s: float, f: float, min_cash: float, max_coin: float) -> tuple[float, float]:
    """The feasible interval of one float parameter with the others fixed: the targets keep the headroom."""
    cap = max_coin - HEADROOM
    if name == "coin_share":
        return 0.0, min(1.0 - min_cash - HEADROOM, cap / max(f, 1.0 - f))
    if name == "btc_share":
        return max(0.0, 1.0 - cap / s), min(1.0, cap / s)
    return 0.0, math.inf  # band_rel: any band >= 0


def plateau_step(params: Mapping, name: str, factor: float, limits: Mapping) -> tuple[dict, str]:
    """One G5 step of one fold's chosen ``params``: ``name`` moved alone by ``factor`` (PLAN.md section 9).

    - ``every``: down (factor < 1) = max(1, min(round(factor*e), e - 1)), up = max(round(factor*e), e + 1), rounded
      half up. It is never clipped; e = 1 going down cannot move ("at the limit").
    - ``coin_share``, ``btc_share``, ``band_rel``: v * factor, clipped to the feasible set with headroom, the other
      parameters unmoved: s <= 1 - min_cash - h and s*max(f, 1 - f) <= max_coin - h (and 0 <= f <= 1). A value
      the clip moved is "clipped"; a step the clip leaves at or behind v (it cannot move) repeats v, "at the
      limit"; otherwise "free".

    The stepped params pass ``check_targets`` with the limits and :data:`HEADROOM` (a refusal there is a bug in
    the clip, raised as ``ValueError``). Returns (params with exactly the 4 keys, mark).
    """
    s, f, b, every = _parse(params)
    min_cash, max_coin = _limit_values(limits)
    if name not in PARAM_NAMES:
        raise ValueError(f"plateau_step: name must be one of {PARAM_NAMES}, got {name!r}")
    factor = _real(factor, "factor", 0.0, low_inclusive=False)
    if factor == 1.0:
        raise ValueError("plateau_step: factor must not be 1")
    out: dict = {"coin_share": s, "btc_share": f, "band_rel": b, "every": every}
    if name == "every":
        if factor < 1:
            new = max(1, min(_half_up(factor * every), every - 1))
        else:
            new = max(_half_up(factor * every), every + 1)
        mark = "at the limit" if new == every else "free"
    else:
        value = out[name]
        raw = value * factor
        low, high = _feasible(name, s, f, min_cash, max_coin)
        new = min(max(raw, low), high)
        if (new <= value) if factor > 1 else (new >= value):
            new, mark = value, "at the limit"
        elif new != raw:
            mark = "clipped"
        else:
            mark = "free"
    out[name] = new
    w_btc, w_eth = targets(out)
    check_targets(w_btc, w_eth, min_cash=min_cash, max_coin=max_coin, headroom=HEADROOM)
    return out, mark


def _step_mark(marks: Sequence[str]) -> str:
    """The most restrictive fold mark: "at the limit" > "clipped" > "free"."""
    if "at the limit" in marks:
        return "at the limit"
    if "clipped" in marks:
        return "clipped"
    return "free"


def plateau_steps(chosen: Sequence[Mapping], limits: Mapping) -> list[dict]:
    """The 8 G5 steps, each applied to every fold's chosen params at once, in the order coin_share, btc_share,
    band_rel, every, each x0.8 then x1.2. Each step: ``param``, ``factor``, ``params`` (one dict per fold, in
    ``chosen``'s order), ``fold_marks`` and ``mark`` (module docstring)."""
    if not chosen:
        raise ValueError("plateau_steps: chosen must hold every fold's chosen params")
    steps = []
    for name in PARAM_NAMES:
        for factor in PLATEAU_FACTORS:
            pairs = [plateau_step(p, name, factor, limits) for p in chosen]
            marks = [m for _, m in pairs]
            steps.append(
                {
                    "param": name,
                    "factor": factor,
                    "params": [p for p, _ in pairs],
                    "fold_marks": marks,
                    "mark": _step_mark(marks),
                }
            )
    return steps


def plateau_verdict(sharpe_s: float, step_sharpes: Sequence[float], marks: Sequence[str]) -> str:
    """G5: "PASS" if Sharpe(S) > 0 and all 8 step Sharpes >= 0.7 * Sharpe(S); "PASS (weak)" if it passes and 3 or
    more step marks are "clipped" or "at the limit"; else "FAIL" (a NaN anywhere fails)."""
    n = 2 * len(PARAM_NAMES)
    if len(step_sharpes) != n or len(marks) != n or any(m not in MARKS for m in marks):
        raise ValueError(f"plateau_verdict: needs {n} step Sharpes and {n} marks from {MARKS}")
    passed = sharpe_s > 0 and all(x >= PLATEAU_KEEP * sharpe_s for x in step_sharpes)
    if not passed:
        return "FAIL"
    return "PASS (weak)" if sum(m != "free" for m in marks) >= 3 else "PASS"


# ------------------------------------------------------------------------------------------ G8, regimes


def regime_table(
    btc_close: pd.Series, kept: pd.DatetimeIndex, threshold: float = REGIME_THRESHOLD
) -> pd.DataFrame:
    """G8 regime labels of the kept rows (daily bars; PLAN.md section 9).

    ``btc_close``: BTC closes on the Kraken panel's index (``panel[("BTC", "close")]``); ``kept``: the stitched kept
    closes (strictly increasing; each a panel close other than the first). Per kept row: ``month`` = the UTC month
    ("YYYY-MM") of its bar's day (close time - 1 day); ``btc_ret`` = close / previous panel close - 1;
    ``month_ret`` = the product of (1 + btc_ret) over that month's kept rows, in time order, - 1; ``regime`` =
    "bull" if month_ret >= threshold, "bear" if <= -threshold, else "sideways".
    """
    threshold = _real(threshold, "threshold", 0.0, low_inclusive=False)
    idx = pd.DatetimeIndex(kept)
    pos = btc_close.index.get_indexer(idx)
    if not idx.is_monotonic_increasing or idx.has_duplicates or (pos < 1).any():
        raise ValueError(
            "regime_table: kept must be strictly increasing panel closes, none of them the first"
        )
    close = btc_close.to_numpy(dtype=float)
    ret = close[pos] / close[pos - 1] - 1.0
    months = (idx - pd.Timedelta(days=1)).strftime("%Y-%m").tolist()
    growth: dict[str, float] = {}
    for month, r in zip(months, ret.tolist(), strict=True):
        growth[month] = growth.get(month, 1.0) * (1.0 + r)
    month_ret = np.array([growth[m] - 1.0 for m in months])
    regime = np.where(month_ret >= threshold, "bull", np.where(month_ret <= -threshold, "bear", "sideways"))
    return pd.DataFrame(
        {"month": months, "btc_ret": ret, "month_ret": month_ret, "regime": regime.astype(object)}, index=idx
    )


def _log_growth(returns: pd.Series, index: pd.Index, name: str) -> np.ndarray:
    if not isinstance(returns, pd.Series) or not returns.index.equals(index):
        raise ValueError(f"regime_split: {name} must be a Series on the regime table's index")
    r = returns.to_numpy(dtype=float)
    if not (np.isfinite(r).all() and (r > -1.0).all()):
        raise ValueError(f"regime_split: {name} must be finite and > -1")
    return np.log1p(r)


def regime_split(returns: pd.Series, table: pd.DataFrame, benchmark: pd.Series | None = None) -> dict:
    """G8: profit per regime = ``math.fsum`` of ln(1 + r) over its rows (``table`` from :func:`regime_table`).

    Returns ``profit`` and ``share`` (profit / total; NaN when total is 0) per regime, ``total`` (fsum over every
    row), ``rows`` and ``months`` per regime, ``pass`` (total > 0 and every regime's profit <= total / 2) and, with
    ``benchmark`` (B4 on the same rows), ``excess`` per regime and ``excess_total`` of ln(1 + S) - ln(1 + B4).
    """
    lr = _log_growth(returns, table.index, "returns")
    labels = table["regime"].to_numpy()
    if not np.isin(labels, REGIMES).all():
        raise ValueError(f"regime_split: regimes must be in {REGIMES}")
    total = math.fsum(lr.tolist())
    profit = {g: math.fsum(lr[labels == g].tolist()) for g in REGIMES}
    out = {
        "profit": profit,
        "total": total,
        "share": {g: profit[g] / total if total != 0.0 else math.nan for g in REGIMES},
        "rows": {g: int((labels == g).sum()) for g in REGIMES},
        "months": {g: int(table.loc[labels == g, "month"].nunique()) for g in REGIMES},
        "pass": bool(total > 0.0 and all(profit[g] <= total / 2.0 for g in REGIMES)),
    }
    if benchmark is not None:
        excess = lr - _log_growth(benchmark, table.index, "benchmark")
        out["excess"] = {g: math.fsum(excess[labels == g].tolist()) for g in REGIMES}
        out["excess_total"] = math.fsum(excess.tolist())
    return out


# ------------------------------------------------------------------------------------------ E1 and E2


def e1_rank(s_returns: pd.Series, b3_returns) -> dict:
    """E1: S's Sharpe (``annualized_sharpe``, 365) against the B3 draws' Sharpes (one row per draw, folds
    stitched). Returns ``sharpe``, ``draw_sharpes``, ``p5``, ``p50``, ``p95`` (``np.percentile``, linear),
    ``rank_p`` = (1 + #{draw >= S}) / (n_draws + 1) and ``holds`` = Sharpe(S) > p95."""
    s = np.asarray(s_returns, dtype=float)
    m = np.asarray(b3_returns, dtype=float)
    if s.ndim != 1 or m.ndim != 2 or m.shape[0] < 1 or m.shape[1] != len(s):
        raise ValueError("e1_rank: b3_returns must have one row per draw and one column per kept row of S")
    sharpe_s = stats.annualized_sharpe(s)
    draws = np.array([stats.annualized_sharpe(row) for row in m])
    pct = percentiles(draws, (5, 50, 95))
    return {
        "sharpe": sharpe_s,
        "draw_sharpes": draws,
        **pct,
        "rank_p": (1 + int(np.sum(draws >= sharpe_s))) / (len(draws) + 1),
        "holds": bool(sharpe_s > pct["p95"]),
    }


def paired_bootstrap(
    s: pd.Series,
    b: pd.Series,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    mean_block: float = MEAN_BLOCK,
    seed: int = 0,
) -> dict:
    """E2's one-sided paired bootstrap (PLAN.md section 10).

    D = annualized_sharpe(s) - annualized_sharpe(b); ``rng = np.random.default_rng(seed)``; each resample draws
    ``stationary_bootstrap_indices(n, mean_block, rng)`` once and applies the same indices to s and b: D* =
    annualized_sharpe(s[idx]) - annualized_sharpe(b[idx]). p = (1 + #{D* <= 0}) / (n_resamples + 1). ``s`` and
    ``b`` are Series on the same index (the stitched kept closes). Returns ``d``, ``p``, ``d_star``, ``holds`` (D >
    0 and p < 0.05), ``n_resamples``, ``mean_block`` and ``seed``.
    """
    if not (isinstance(s, pd.Series) and isinstance(b, pd.Series) and s.index.equals(b.index)):
        raise ValueError("paired_bootstrap: s and b must be Series on the same index")
    n_resamples = _count(n_resamples, "n_resamples", 1)
    seed = _count(seed, "seed", 0)
    x, y = s.to_numpy(dtype=float), b.to_numpy(dtype=float)
    d = stats.annualized_sharpe(x) - stats.annualized_sharpe(y)
    rng = np.random.default_rng(seed)
    d_star = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = stationary_bootstrap_indices(len(x), mean_block, rng)
        d_star[i] = stats.annualized_sharpe(x[idx]) - stats.annualized_sharpe(y[idx])
    p = (1 + int(np.sum(d_star <= 0.0))) / (n_resamples + 1)
    return {
        "d": d,
        "p": p,
        "d_star": d_star,
        "holds": bool(d > 0.0 and p < 0.05),
        "n_resamples": n_resamples,
        "mean_block": mean_block,
        "seed": seed,
    }


# --------------------------------------------------------------------- what the report does not return


def _report_matrix(study: str, out_dir: str | Path) -> pd.DataFrame:
    return load_trial_returns(study, out_dir).dropna()


def report_trial_sharpes(studies: Iterable[str], out_dir: str | Path) -> list[float]:
    """The trial Sharpes ``overfitting_report`` builds its DSR from (module docstring), for the strict DSR:
    ``stats.deflated_sharpe_ratio(S, report_trial_sharpes(studies, out_dir), n_trials=N_raw + 21)``."""
    sharpes: list[float] = []
    for study in studies:
        m = _report_matrix(study, out_dir)
        if m.shape[1] < 2:
            continue
        sharpes += [stats.sharpe(m[c]) for c in m.columns]
    return sharpes


def study_pbo(study: str, out_dir: str | Path) -> dict | None:
    """One study's PBO as ``overfitting_report`` computes it: ``stats.pbo(m.to_numpy(), n_blocks=10)`` (keys
    ``pbo``, ``logits``, ``n_combinations``, ``n_trials``), or None when the report skips the study (fewer than
    2 completed trials). The mean of the non-None ``pbo`` values over the report's studies is its ``pbo_mean``."""
    m = _report_matrix(study, out_dir)
    if m.shape[1] < 2:
        return None
    return stats.pbo(m.to_numpy(), n_blocks=10)


def stable_neighbours(trials: pd.DataFrame, specs: Sequence[Param], k: int = 10) -> dict:
    """The neighbourhood ``stable_region(trials, specs, k)`` chose (module docstring). Returns ``trial_number``
    and ``neighbourhood_score`` (equal to ``stable_region``'s) and ``neighbours``: a DataFrame of the k nearest
    completed trials in argsort order (the chosen trial among them) with ``number``, ``value``, ``distance`` (in
    unit space) and ``params_<name>`` per spec."""
    done = trials[(trials["state"] == "COMPLETE") & np.isfinite(trials["value"])].reset_index(drop=True)
    if done.empty:
        raise ValueError("no completed trials")
    units = np.array([[p.to_unit(row[f"params_{p.name}"]) for p in specs] for _, row in done.iterrows()])
    values = done["value"].to_numpy(float)
    k = min(k, len(done))
    dist = np.linalg.norm(units[:, None, :] - units[None, :, :], axis=2)
    neighbours = np.argsort(dist, axis=1)[:, :k]
    hood = np.sort(values[neighbours], axis=1).mean(axis=1)
    tied = np.flatnonzero(hood == hood.max())
    i = int(tied[np.argmax(values[tied])])
    rows = neighbours[i]
    table = done.loc[rows, ["number", "value", *(f"params_{p.name}" for p in specs)]].reset_index(drop=True)
    table.insert(2, "distance", dist[i, rows])
    return {
        "trial_number": int(done.loc[i, "number"]),
        "neighbourhood_score": float(hood[i]),
        "neighbours": table,
    }
