"""Reference backtester: small pure-Python dip-buy and benchmark rules with a DEX cost model.

**Tests and demos only; never in reports** (AGENTS.md hard rule 3: only Nautilus results count). This
module is the executable statement of the backtest contract in ``lab/runner/interface.py``. The
Nautilus runner must reproduce it (contract suite and parity test).

Execution model (identical for every rule here, and required of every runner)
------------------------------------------------------------------------------
- A rule decides at the close of bar t, using data up to and including that close.
- The order fills at the OPEN of bar t+1, never on bar t. Decisions taken at the last close are never filled.
- Between trades the portfolio holds coin units, so the risky weight drifts with the price. Nothing is
  rebalanced for free (TESTING.md bug #4).
- Per bar t (t >= 1), with g = open[t]/close[t-1] - 1, h = close[t]/open[t] - 1, r = close[t]/close[t-1] - 1
  and w0 = position[t-1]:

  - **fill** (target weight w with turnover > 0):
    w_drift = w0 (1+g) / (1 + w0 g), turnover = |w - w_drift|,
    V_open = V[t-1] (1 + w0 g) (USD, just before the trade), trade_usd = turnover * V_open,
    cost = turnover * costs.rate(trade_usd) + costs.gas_fraction(V_open), and

        1 + ret[t] = (1 + w0 g) (1 - cost) (1 + w h)        position[t] = w (1+h) / (1 + w h)

  - **no fill**: 1 + ret[t] = 1 + w0 r and position[t] = w0 (1+r) / (1 + w0 r); turnover = cost = 0.

  A target equal to the drifted weight is not a fill: it trades nothing and pays nothing.
- A round trip runs from a fill out of a flat book (position 0) to the fill that returns it to 0. Its
  return is V_after_exit / V_before_entry - 1, costs of both legs included. A round trip still open at the
  last bar is marked to market at the last close for the trade log only (no exit cost). Because every
  round trip starts and ends flat, ``prod(1 + trade_returns) == prod(1 + ret)`` for every rule here.

Result: the DataFrame described in ``lab/runner/interface.py`` (``ret``, ``position``, ``turnover``,
``cost`` on ``bars.index``) with ``attrs["trade_returns"]`` (np.ndarray, exit order), ``attrs["n_trades"]``
(number of fills: entries + exits + rebalances) and ``attrs["trades"]`` (one row per fill: ``ts``,
``side``, ``price`` (the fill open), ``weight_before`` (drifted), ``weight_after`` (target), ``turnover``,
``cost``).

Bars are daily: annualised volatility uses sqrt(365) (crypto trades every day). Parameters arrive as a
dict. Unknown keys, missing required keys and out-of-range values raise ``ValueError``, so a typo
such as ``stop_loss`` cannot be silently ignored.

pandas caveat: ``attrs`` holds arrays and a DataFrame, and pandas copies ``attrs`` onto every column or
slice taken from the result. ``pd.concat`` of such pieces raises ValueError (it compares the attrs, even for
two columns of the same result) and ``to_parquet`` raises TypeError (it JSON-encodes them). Drop the attrs
first (``piece.attrs = {}``) or build a new frame from ``.to_numpy()``.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from lab.config import load_yaml
from lab.runner.interface import validate_bars

__all__ = [
    "PERIODS_PER_YEAR",
    "Costs",
    "buy_and_hold",
    "constant_mix",
    "dip_buy",
    "random_entry",
    "realised_vol",
    "scheduled",
]

PERIODS_PER_YEAR = 365  # daily crypto bars: annualised volatility = per-bar volatility * sqrt(365)
_BPS = 1e4
_COST_KEYS = ("pool_fee_bps", "aggregator_fee_bps", "slippage_bps", "gas_usd_per_trade", "stress_multiplier")
_REQUIRED = object()


# ----------------------------------------------------------------------------------------------- checks


def _real(value, name: str, low: float, *, low_inclusive: bool, high: float = math.inf, high_inclusive=False):
    """``float(value)`` if it is a finite real number in the interval, else ``ValueError``."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a number, got {value!r}")
    x = float(value)
    above = x > low or (low_inclusive and x == low)
    below = x < high or (high_inclusive and x == high)
    if not (math.isfinite(x) and above and below):
        interval = f"{'[' if low_inclusive else '('}{low}, {high}{']' if high_inclusive else ')'}"
        raise ValueError(f"{name} must be in {interval}, got {value!r}")
    return x


def _check_params(rule: str, params, allowed: frozenset[str]) -> Mapping:
    if not isinstance(params, Mapping):
        raise ValueError(f"{rule}: params must be a dict, got {type(params).__name__}")
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"{rule}: unknown params {unknown}; allowed: {sorted(allowed)}")
    return params


def _get(params: Mapping, key: str, default):
    value = params.get(key, default)
    if value is _REQUIRED:
        raise ValueError(f"missing required param {key!r}")
    return value


def _param_float(params: Mapping, key: str, default=_REQUIRED, **bounds) -> float:
    return _real(_get(params, key, default), key, **bounds)


def _param_int(params: Mapping, key: str, default=_REQUIRED, minimum: int = 1) -> int:
    """An integer >= ``minimum``. Integral floats such as 5.0 (a search space may produce them) are accepted."""
    value = _get(params, key, default)
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not float(value).is_integer():
        raise ValueError(f"{key} must be an integer, got {value!r}")
    if int(value) < minimum:
        raise ValueError(f"{key} must be >= {minimum}, got {value!r}")
    return int(value)


def _is_off(value) -> bool:
    """True for None or a numeric zero: ``stop=0`` and ``stop=None`` both mean "no stop"."""
    return value is None or (isinstance(value, numbers.Real) and not isinstance(value, bool) and value == 0)


# ------------------------------------------------------------------------------------------------ costs


@dataclass(frozen=True)
class Costs:
    """Per-fill DEX costs from ``config/costs.yaml``: pool fee + aggregator fee + size-based slippage + gas.

    Units: fees and slippage are basis points of traded notional; ``slippage_bps`` is a table of
    ``(trade_usd, bps)`` points with strictly increasing sizes; gas is USD per fill (we sponsor it, so it is
    our cost); ``capital_usd`` is the starting portfolio value. The portfolio compounds from it, so trade
    sizes in USD (which set slippage) and the gas share follow the equity curve. Invalid values raise
    ``ValueError``.
    """

    # Defaults: the 2026-11 placeholders, kept as a fixed cost model for tests. Runs read config/costs.yaml
    # through from_yaml() (measured values since 2026-11-25; TESTING.md #63).
    pool_fee_bps: float = 5.0
    aggregator_fee_bps: float = 0.0
    slippage_bps: tuple[tuple[float, float], ...] = ((100.0, 10.0), (1000.0, 15.0), (10000.0, 30.0))
    gas_usd_per_trade: float = 0.10
    stress_multiplier: float = 2.0
    capital_usd: float = 10_000.0

    def __post_init__(self) -> None:
        for name in ("pool_fee_bps", "aggregator_fee_bps", "gas_usd_per_trade"):
            object.__setattr__(self, name, _real(getattr(self, name), name, 0.0, low_inclusive=True))
        for name in ("stress_multiplier", "capital_usd"):
            object.__setattr__(self, name, _real(getattr(self, name), name, 0.0, low_inclusive=False))
        try:
            points = [tuple(point) for point in self.slippage_bps]
        except TypeError:
            points = []
        if not points or any(len(point) != 2 for point in points):
            raise ValueError(
                f"slippage_bps must be a non-empty sequence of (trade_usd, bps) pairs, got {self.slippage_bps!r}"
            )
        sizes = [_real(size, "slippage trade size (USD)", 0.0, low_inclusive=False) for size, _ in points]
        bps = [_real(b, "slippage (bps)", 0.0, low_inclusive=True) for _, b in points]
        if any(b <= a for a, b in zip(sizes, sizes[1:], strict=False)):
            raise ValueError(f"slippage trade sizes must be strictly increasing, got {sizes}")
        object.__setattr__(self, "slippage_bps", tuple(zip(sizes, bps, strict=True)))

    @classmethod
    def from_yaml(cls, path: str | Path | None = None, capital_usd: float = 10_000.0) -> Costs:
        """Costs from ``config/costs.yaml`` (default) or another ``.yaml`` file with the same keys.

        Every cost key must be present (a missing key is an error, never a silent default). Other keys such
        as ``venue`` are ignored. ``slippage_bps`` maps trade size in USD (string or number) to bps.
        """
        if path is None:
            raw = load_yaml("costs")
        else:
            p = Path(path)
            if p.suffix != ".yaml":
                raise ValueError(f"costs file must be a .yaml file, got {p}")
            raw = load_yaml(p.stem, p.parent)
        missing = [key for key in _COST_KEYS if key not in raw]
        if missing:
            raise ValueError(f"costs config is missing {missing}")
        table = raw["slippage_bps"]
        if not isinstance(table, Mapping):
            raise ValueError(f"slippage_bps must map trade size in USD to bps, got {table!r}")
        try:
            points = sorted(((float(size), bps) for size, bps in table.items()), key=lambda point: point[0])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"slippage_bps sizes must be numbers, got {list(table)}") from exc
        return cls(
            pool_fee_bps=raw["pool_fee_bps"],
            aggregator_fee_bps=raw["aggregator_fee_bps"],
            slippage_bps=tuple(points),
            gas_usd_per_trade=raw["gas_usd_per_trade"],
            stress_multiplier=raw["stress_multiplier"],
            capital_usd=capital_usd,
        )

    @classmethod
    def zero(cls) -> Costs:
        """No fees, no slippage, no gas: for identities only (a zero-cost backtest is not a result)."""
        return cls(
            pool_fee_bps=0.0, aggregator_fee_bps=0.0, slippage_bps=((1.0, 0.0),), gas_usd_per_trade=0.0
        )

    def slippage(self, trade_usd: float) -> float:
        """Slippage in bps for a trade of ``trade_usd``: piecewise-linear in log10(size) between the table
        points, flat below the smallest point, and above the largest point extended along the last segment's
        slope (pessimistic: never extended downward, so it never falls below the largest point's value).
        """
        x = _real(trade_usd, "trade_usd", 0.0, low_inclusive=True)
        sizes = [size for size, _ in self.slippage_bps]
        bps = [b for _, b in self.slippage_bps]
        if x <= sizes[0]:
            return bps[0]
        lx = math.log10(x)
        for i in range(1, len(sizes)):
            if x <= sizes[i]:
                la, lb = math.log10(sizes[i - 1]), math.log10(sizes[i])
                return bps[i - 1] + (bps[i] - bps[i - 1]) * (lx - la) / (lb - la)
        if len(sizes) == 1:
            return bps[0]
        la, lb = math.log10(sizes[-2]), math.log10(sizes[-1])
        slope = max((bps[-1] - bps[-2]) / (lb - la), 0.0)
        return bps[-1] + slope * (lx - lb)

    def rate(self, trade_usd: float) -> float:
        """Proportional cost of a trade of ``trade_usd`` as a fraction of its notional: (pool + aggregator + slippage) / 1e4."""
        return (self.pool_fee_bps + self.aggregator_fee_bps + self.slippage(trade_usd)) / _BPS

    def gas_fraction(self, portfolio_usd: float) -> float:
        """Gas for one fill as a fraction of a portfolio worth ``portfolio_usd`` (> 0)."""
        return self.gas_usd_per_trade / _real(portfolio_usd, "portfolio_usd", 0.0, low_inclusive=False)

    def stressed(self, k: float | None = None) -> Costs:
        """Every cost, gas included, multiplied by ``k`` (default ``stress_multiplier``; finalists rerun at 2x)."""
        k = self.stress_multiplier if k is None else _real(k, "k", 0.0, low_inclusive=False)
        return replace(
            self,
            pool_fee_bps=self.pool_fee_bps * k,
            aggregator_fee_bps=self.aggregator_fee_bps * k,
            slippage_bps=tuple((size, b * k) for size, b in self.slippage_bps),
            gas_usd_per_trade=self.gas_usd_per_trade * k,
        )


# ------------------------------------------------------------------------------------------- the engine


@dataclass
class _State:
    """What a rule may look at when it decides at the close of bar t (all of it known at that close)."""

    position: float = 0.0  # risky weight at the close of bar t
    entry_bar: int | None = None  # bar whose open filled the entry of the open round trip (None when flat)
    entry_price: float = math.nan  # that fill price (the open of entry_bar)
    exit_bar: int | None = None  # bar whose open filled the most recent exit to flat


Decide = Callable[[int, _State], float | None]


def _simulate(bars: pd.DataFrame, costs: Costs, decide: Decide) -> pd.DataFrame:
    """Run ``decide`` at every close (it returns a target weight, or None for no order).

    The order decided at close t fills at the open of t+1, so the decision at the last close is never filled:
    the loop ends before it is used.
    """
    o = bars["open"].to_numpy(dtype=float).tolist()
    c = bars["close"].to_numpy(dtype=float).tolist()
    n = len(c)
    ret, pos, turnover, cost = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    fills: list[tuple[int, float, float, float, float, float]] = []
    trade_returns: list[float] = []
    state = _State()
    value = entry_value = costs.capital_usd  # USD at the last close; USD just before the open entry
    target = decide(0, state)
    for t in range(1, n):
        w0 = pos[t - 1]
        g = o[t] / c[t - 1] - 1.0
        drifted = w0 * (1.0 + g) / (1.0 + w0 * g)
        traded = 0.0 if target is None else abs(target - drifted)
        if traded > 0.0:
            h = c[t] / o[t] - 1.0
            v_open = value * (1.0 + w0 * g)
            k = traded * costs.rate(traded * v_open) + costs.gas_fraction(v_open)
            if k >= 1.0:
                raise ValueError(
                    f"costs of the fill on {bars.index[t]} are {k:.1%} of a portfolio worth {v_open:.4g} USD: "
                    "it cannot pay them (raise capital_usd or check the cost model)"
                )
            growth = (1.0 + w0 * g) * (1.0 - k) * (1.0 + target * h)
            pos[t] = target * (1.0 + h) / (1.0 + target * h)
            turnover[t], cost[t] = traded, k
            fills.append((t, o[t], drifted, target, traded, k))
            if w0 == 0.0:
                # out of a flat book: a round trip starts; value at the open == value at the last close
                entry_value = value
                state.entry_bar, state.entry_price = t, o[t]
        else:
            r = c[t] / c[t - 1] - 1.0
            growth = 1.0 + w0 * r
            pos[t] = w0 * (1.0 + r) / (1.0 + w0 * r)
        ret[t] = growth - 1.0
        value *= growth
        if traded > 0.0 and target == 0.0:  # back to flat: the round trip ends at the exit open
            trade_returns.append(value / entry_value - 1.0)
            state.entry_bar, state.exit_bar = None, t
        state.position = pos[t]
        target = decide(t, state)
    if state.entry_bar is not None:  # still open: marked to market at the last close, no exit cost
        trade_returns.append(value / entry_value - 1.0)
    result = pd.DataFrame(
        {"ret": ret, "position": pos, "turnover": turnover, "cost": cost}, index=bars.index, dtype=float
    )
    result.attrs["trade_returns"] = np.asarray(trade_returns, dtype=float)
    result.attrs["n_trades"] = len(fills)
    result.attrs["trades"] = _fills_frame(bars.index, fills)
    return result


def _fills_frame(index: pd.DatetimeIndex, fills: list[tuple]) -> pd.DataFrame:
    cols = list(zip(*fills, strict=True)) or [()] * 6
    bar = np.asarray(cols[0], dtype=np.int64)
    before = np.asarray(cols[2], dtype=float)
    after = np.asarray(cols[3], dtype=float)
    return pd.DataFrame(
        {
            "ts": index[bar],
            "side": np.where(after > before, "buy", "sell"),
            "price": np.asarray(cols[1], dtype=float),
            "weight_before": before,
            "weight_after": after,
            "turnover": np.asarray(cols[4], dtype=float),
            "cost": np.asarray(cols[5], dtype=float),
        }
    )


def _prepare(bars: pd.DataFrame, costs: Costs | None) -> Costs:
    validate_bars(bars)
    if costs is None:
        return Costs.from_yaml()
    if not isinstance(costs, Costs):
        raise ValueError(f"costs must be a Costs instance or None, got {type(costs).__name__}")
    return costs


# -------------------------------------------------------------------------------------------- the rules


def realised_vol(close: np.ndarray, window: int) -> np.ndarray:
    """Annualised realised volatility at each bar's close: sample std (ddof=1) of the last ``window`` log
    returns ending at that close, times sqrt(365). NaN until ``window`` returns exist (bars 0..window-1).
    Each value depends only on its own window (no running sums), so the past never changes with the future.
    """
    close = np.asarray(close, dtype=float)
    vol = np.full(len(close), np.nan)
    if len(close) > window:
        log_ret = np.log(close[1:] / close[:-1])
        vol[window:] = sliding_window_view(log_ret, window).std(axis=1, ddof=1) * math.sqrt(PERIODS_PER_YEAR)
    return vol


def _dip_signal(close: np.ndarray, drop: float, lookback: int) -> np.ndarray:
    """True at bar t when close[t] / max(close[t-lookback..t]) - 1 <= -drop; False before a full window."""
    signal = np.zeros(len(close), dtype=bool)
    if len(close) > lookback:
        peak = sliding_window_view(close, lookback + 1).max(axis=1)
        signal[lookback:] = close[lookback:] / peak - 1.0 <= -drop
    return signal


def _entry_size(
    close: np.ndarray,
    weight: float,
    vol_target: float | None,
    vol_lookback: int,
    forecast: np.ndarray | None = None,
) -> np.ndarray:
    """Target weight of an entry decided at each close: ``weight``, or min(weight, vol_target / vol) when
    vol-targeting. NaN while the volatility is undefined (no entry can be sized yet). Zero realised volatility
    puts no cap on the weight.

    ``forecast`` (optional): an annualised volatility forecast per close. Where it is finite it replaces the
    realised volatility; where it is NaN or infinite (e.g. before the first model is trained) the realised
    volatility is used. A finite forecast <= 0 is not a usable forecast: no entry is sized from it.
    """
    if vol_target is None:
        return np.full(len(close), weight)
    vol = realised_vol(close, vol_lookback)
    if forecast is not None:
        vol = np.where(np.isfinite(forecast), forecast, vol)
    cap = np.divide(vol_target, vol, out=np.full(len(close), np.inf), where=vol > 0)
    size = np.minimum(weight, cap)
    size[np.isnan(vol)] = np.nan
    if forecast is not None:
        size[np.isfinite(forecast) & (forecast <= 0)] = np.nan
    return size


_DIP_PARAMS = frozenset({"drop", "lookback", "stop", "hold", "weight", "vol_target", "vol_lookback", "vol_col"})


def dip_buy(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Buy a dip, exit on a stop or after a holding period.

    params:
    - ``drop`` (required, fraction in (0, 1)): entry signal at close t when flat and
      close[t] / max(close[t-lookback..t]) - 1 <= -drop (needs a full window: t >= lookback).
    - ``lookback`` (required, bars >= 1).
    - ``stop`` (fraction in (0, 1); 0 or None = no stop): exit signal at close t when
      close[t] <= entry_fill_price * (1 - stop). The entry fill price is the open the entry filled at.
    - ``hold`` (bars >= 1; None = no limit): exit signal at the close of the ``hold``-th bar in the position,
      so the exit fills at the open of entry_bar + hold.
    - ``weight`` (fraction in (0, 1], default 1.0): target weight when in.
    - ``vol_target`` (annualised volatility > 0; None = off) and ``vol_lookback`` (bars >= 2, default 20):
      weight = min(weight, vol_target / realised_vol) at the signal close. While the volatility is still
      undefined, entry signals are ignored.
    - ``vol_col`` (column name; needs ``vol_target``): size from a model's ANNUALISED volatility forecast in
      ``bars[vol_col]`` instead, the value at the signal close (it must be known at that close, i.e. computed
      point in time, such as ``walk_forward_predict`` output). Where the forecast is NaN or infinite (before the
      first model exists) the realised volatility is used; a forecast <= 0 means no entry.

    Every signal fills at the next open. After an exit fills on bar x, no entry is decided at the close of
    bar x, so the earliest re-entry fills at x + 2 (TESTING.md bug #5: an exit never re-enters on its own bar).
    ``costs=None`` reads ``config/costs.yaml``.
    """
    p = _check_params("dip_buy", params, _DIP_PARAMS)
    drop = _param_float(p, "drop", low=0.0, low_inclusive=False, high=1.0)
    lookback = _param_int(p, "lookback")
    stop = None if _is_off(p.get("stop")) else _param_float(p, "stop", low=0.0, low_inclusive=False, high=1.0)
    hold = None if p.get("hold") is None else _param_int(p, "hold")
    weight = _param_float(p, "weight", 1.0, low=0.0, low_inclusive=False, high=1.0, high_inclusive=True)
    vol_target = (
        None if p.get("vol_target") is None else _param_float(p, "vol_target", low=0.0, low_inclusive=False)
    )
    vol_lookback = _param_int(p, "vol_lookback", 20, minimum=2)
    vol_col = p.get("vol_col")
    costs = _prepare(bars, costs)
    forecast = None
    if vol_col is not None:
        if vol_target is None:
            raise ValueError("vol_col needs vol_target (the forecast is only used to size by volatility)")
        if not isinstance(vol_col, str) or vol_col not in bars.columns:
            raise ValueError(f"vol_col must name a column of bars, got {vol_col!r}")
        forecast = bars[vol_col].to_numpy(dtype=float)

    close = bars["close"].to_numpy(dtype=float)
    signal = _dip_signal(close, drop, lookback).tolist()
    size = _entry_size(close, weight, vol_target, vol_lookback, forecast).tolist()
    closes = close.tolist()

    def decide(t: int, s: _State) -> float | None:
        if s.entry_bar is None:
            if s.exit_bar == t or not signal[t] or math.isnan(size[t]):
                return None  # just exited on this bar, no dip, or the entry can't be sized yet
            return size[t]
        if stop is not None and closes[t] <= s.entry_price * (1.0 - stop):
            return 0.0
        if hold is not None and t - s.entry_bar + 1 >= hold:
            return 0.0
        return None

    return _simulate(bars, costs, decide)


def buy_and_hold(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Buy ``weight`` (fraction in (0, 1], default 1.0) at the open of bar 1 and hold coin units to the end.

    With weight < 1 the weight drifts with the price. It is never rebalanced.
    """
    p = _check_params("buy_and_hold", params, frozenset({"weight"}))
    weight = _param_float(p, "weight", 1.0, low=0.0, low_inclusive=False, high=1.0, high_inclusive=True)
    costs = _prepare(bars, costs)
    return _simulate(bars, costs, lambda t, s: weight if t == 0 else None)


def constant_mix(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Hold ``weight`` of the asset, the rest in USDC, and pay to rebalance back to it.

    params: ``weight`` (fraction in (0, 1], default 0.5); ``every`` (bars >= 1, default 1): rebalance
    decisions are taken at the closes of bars 0, every, 2*every, ... and fill at the next open; ``band``
    (fraction in [0, 1), default 0.0): skip a rebalance when |weight at the decision close - target| <= band.
    The initial buy (decided at close 0, filled at the open of bar 1) is not a rebalance and ignores the
    band. Every rebalance pays costs (TESTING.md bug #6). A 50/50 monthly benchmark is
    ``{"weight": 0.5, "every": 30}``.
    """
    p = _check_params("constant_mix", params, frozenset({"weight", "every", "band"}))
    weight = _param_float(p, "weight", 0.5, low=0.0, low_inclusive=False, high=1.0, high_inclusive=True)
    every = _param_int(p, "every", 1)
    band = _param_float(p, "band", 0.0, low=0.0, low_inclusive=True, high=1.0)
    costs = _prepare(bars, costs)

    def decide(t: int, s: _State) -> float | None:
        if t % every:
            return None
        if s.position == 0.0 or abs(s.position - weight) > band:
            return weight
        return None

    return _simulate(bars, costs, decide)


def random_entry(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """The luck benchmark: ``n_trades`` round trips at random times, each held ``hold`` bars.

    params: ``n_trades`` (round trips >= 0, required; ``attrs["n_trades"]`` counts fills, so it is twice
    this), ``hold`` (bars >= 1, required): each entry fills at the open of bar e and its exit at the open of
    bar e + hold; ``seed`` (int >= 0, default 0); ``weight`` (fraction in (0, 1], default 1.0).

    Entry bars are drawn uniformly over every non-overlapping layout in bars 1..n-1 (a round trip occupies
    its entry bar through its exit bar), seeded by ``seed``. The draw depends only on len(bars), never on
    prices. Raises ``ValueError`` if the round trips can't fit: n_trades * (hold + 1) > len(bars) - 1.
    """
    p = _check_params("random_entry", params, frozenset({"n_trades", "hold", "seed", "weight"}))
    n_trips = _param_int(p, "n_trades", minimum=0)
    hold = _param_int(p, "hold")
    seed = _param_int(p, "seed", 0, minimum=0)
    weight = _param_float(p, "weight", 1.0, low=0.0, low_inclusive=False, high=1.0, high_inclusive=True)
    costs = _prepare(bars, costs)
    free = (len(bars) - 1) - n_trips * (hold + 1)
    if free < 0:
        raise ValueError(f"random_entry: {n_trips} round trips of {hold} bars don't fit in {len(bars)} bars")
    # Stars and bars: choose n_trips sorted slots among free + n_trips; trip i starts hold bars later per trip before it.
    slots = np.sort(np.random.default_rng(seed).choice(free + n_trips, size=n_trips, replace=False))
    entries = (1 + slots + np.arange(n_trips) * hold).tolist()
    decisions = {e - 1: weight for e in entries} | {e + hold - 1: 0.0 for e in entries}
    return _simulate(bars, costs, lambda t, s: decisions.get(t))


def scheduled(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Hold the target weight a schedule column names, decided at each close and filled at the next open.

    params: ``col`` (required): the name of a column of ``bars`` that holds, at the close of bar t, the target
    weight in [0, 1] to hold from the open of bar t+1. The column must be known at that close (computed point in
    time from bars up to t, e.g. by :func:`lab.models.dips.schedule_column`); this rule only executes it.

    An order is sent at close t only when the column's value differs from the last target ordered (0 before the
    first order: the book starts flat). Holding a weight therefore holds coin units: the weight drifts with the
    price and is never rebalanced for free (TESTING.md bug #4). A ladder of rising targets (1/3, 2/3, 1) adds to
    one round trip; a return to 0 closes it. A change at the last close is never filled. A column value that is
    not a finite number in [0, 1] raises ``ValueError``.
    """
    p = _check_params("scheduled", params, frozenset({"col"}))
    col = _get(p, "col", _REQUIRED)
    if not isinstance(col, str) or col not in bars.columns or col in ("open", "high", "low", "close", "volume"):
        raise ValueError(f"col must name a schedule column of bars (not a price or volume), got {col!r}")
    costs = _prepare(bars, costs)
    try:
        target = bars[col].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"schedule column {col!r} must hold numbers") from exc
    if not (np.isfinite(target).all() and (target >= 0.0).all() and (target <= 1.0).all()):
        raise ValueError(f"schedule column {col!r} must hold finite target weights in [0, 1]")
    targets = target.tolist()
    last = [0.0]  # the last target ordered

    def decide(t: int, s: _State) -> float | None:
        if targets[t] == last[0]:
            return None
        last[0] = targets[t]
        return targets[t]

    return _simulate(bars, costs, decide)
