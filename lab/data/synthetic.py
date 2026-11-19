"""Synthetic bars for tests and demos only. Never used in a report.

The generator mimics two features of crypto daily data that matter for the lab's statistics:

- **Regimes**: a Markov chain switches between bull, bear and sideways states with different drift and
  volatility, so trend-following and dip-buying rules have something to find (or to be fooled by).
- **Volatility clustering**: GARCH(1,1) shocks with fat-tailed (Student-t) innovations.

ETH is correlated with BTC (shared innovations) and is more volatile. ``shuffled_market`` destroys
all serial structure while keeping each bar's shape, which makes it the luck control: no strategy
should pass validation on it.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

# drift and volatility per bar (log returns), by regime: 0 bull, 1 bear, 2 sideways
_DRIFT = np.array([0.0025, -0.0030, 0.0])
_VOL = np.array([0.030, 0.045, 0.022])
_TRANSITION = np.array(
    [
        [0.985, 0.005, 0.010],
        [0.010, 0.975, 0.015],
        [0.010, 0.008, 0.982],
    ]
)
_START_PRICE = {"BTC": 10_000.0, "ETH": 300.0}
_VOL_MULT = {"BTC": 1.0, "ETH": 1.25}
_GARCH_ALPHA = 0.08
_GARCH_BETA = 0.90
_T_DF = 5
_CORR = 0.8


def _regime_path(n: int, rng: np.random.Generator) -> np.ndarray:
    states = np.empty(n, dtype=int)
    states[0] = 2
    u = rng.random(n)
    cum = np.cumsum(_TRANSITION, axis=1)
    for t in range(1, n):
        states[t] = int(np.searchsorted(cum[states[t - 1]], u[t], side="right"))
    return np.minimum(states, 2)


def _garch_scale(innov: np.ndarray) -> np.ndarray:
    """Unit-variance GARCH(1,1) shocks built from unit-variance innovations."""
    omega = 1.0 - _GARCH_ALPHA - _GARCH_BETA
    out = np.empty_like(innov)
    var = 1.0
    prev = 0.0
    for t, z in enumerate(innov):
        var = omega + _GARCH_ALPHA * prev**2 + _GARCH_BETA * var
        prev = np.sqrt(var) * z
        out[t] = prev
    return out


def _student_t(rng: np.random.Generator, size: int) -> np.ndarray:
    # Student-t scaled to unit variance
    return rng.standard_t(_T_DF, size) / np.sqrt(_T_DF / (_T_DF - 2))


def _bars_from_log_returns(
    log_ret: np.ndarray,
    sigma: np.ndarray,
    start_price: float,
    index: pd.DatetimeIndex,
    rng: np.random.Generator,
) -> pd.DataFrame:
    n = len(log_ret)
    close = start_price * np.exp(np.cumsum(log_ret))
    prev_close = np.concatenate([[start_price], close[:-1]])
    gap = rng.normal(0.0, 0.0005, n)  # tiny open gaps, so open != previous close
    open_ = prev_close * np.exp(gap)
    top = np.maximum(open_, close)
    bottom = np.minimum(open_, close)
    high = top * np.exp(np.abs(rng.normal(0.0, 0.4, n)) * sigma)
    low = bottom * np.exp(-np.abs(rng.normal(0.0, 0.4, n)) * sigma)
    volume = 1_000.0 * np.exp(0.5 * np.abs(log_ret) / np.maximum(sigma, 1e-12) + rng.normal(0.0, 0.3, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def synthetic_market(
    n_days: int = 1500,
    assets: Iterable[str] = ("BTC", "ETH"),
    seed: int = 21,
    start: str = "2019-01-01",
) -> dict[str, pd.DataFrame]:
    """Daily bars for each asset, indexed by bar close time (UTC), sharing one regime path."""
    assets = tuple(assets)
    if n_days < 2:
        raise ValueError("n_days must be at least 2")
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=n_days, freq="D", tz="UTC", name="ts")
    regimes = _regime_path(n_days, rng)
    common = _student_t(rng, n_days)
    market: dict[str, pd.DataFrame] = {}
    for i, asset in enumerate(assets):
        own = _student_t(rng, n_days)
        innov = common if i == 0 else _CORR * common + np.sqrt(1 - _CORR**2) * own
        shocks = _garch_scale(innov)
        mult = _VOL_MULT.get(asset, 1.0 + 0.25 * i)
        sigma = _VOL[regimes] * mult
        log_ret = _DRIFT[regimes] * (1.0 + 0.1 * i) + sigma * shocks
        price0 = _START_PRICE.get(asset, 100.0)
        market[asset] = _bars_from_log_returns(log_ret, sigma, price0, index, rng)
    return market


def synthetic_bars(n_days: int = 1500, seed: int = 21, start: str = "2019-01-01") -> pd.DataFrame:
    """Single-asset (BTC-like) daily bars."""
    return synthetic_market(n_days, assets=("BTC",), seed=seed, start=start)["BTC"]


def shuffled_market(market: dict[str, pd.DataFrame], seed: int = 0) -> dict[str, pd.DataFrame]:
    """Permute the order of bars (jointly across assets) and rebuild prices.

    Each bar keeps its own shape (gap, open-to-close move, wick sizes, volume), so the distribution
    of daily moves is unchanged, but regimes and volatility clusters are destroyed.
    """
    assets = list(market)
    n = len(market[assets[0]])
    rng = np.random.default_rng(seed)
    order = np.concatenate([[0], 1 + rng.permutation(n - 1)])
    out: dict[str, pd.DataFrame] = {}
    for asset in assets:
        bars = market[asset]
        o, h, lo, c, v = (bars[col].to_numpy() for col in ("open", "high", "low", "close", "volume"))
        prev_c = np.concatenate([[o[0]], c[:-1]])
        gap = o / prev_c
        body = c / o
        up = h / np.maximum(o, c)
        down = lo / np.minimum(o, c)
        gap, body, up, down, v = gap[order], body[order], up[order], down[order], v[order]
        # bar 0 stays first (order[0] == 0) and its "previous close" is its own open, so gap[0] == 1
        new_c = o[0] * np.cumprod(gap * body)
        new_o = np.concatenate([[o[0]], new_c[:-1]]) * gap
        out[asset] = pd.DataFrame(
            {
                "open": new_o,
                "high": np.maximum(new_o, new_c) * up,
                "low": np.minimum(new_o, new_c) * down,
                "close": new_c,
                "volume": v,
            },
            index=bars.index,
        )
    return out
