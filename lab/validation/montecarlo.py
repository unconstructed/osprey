"""Monte Carlo checks on drawdowns and execution: how bad could it have been with the same trades in another order?

Conventions
- Returns are simple fractional returns per period (0.01 = 1%), each >= -1 (spot only: you can't lose more than
  everything). Equity compounds from 1.0.
- Drawdowns are negative fractions: -0.19 means equity fell 19% below its running peak. The starting equity 1.0
  counts as a peak, so a first-period loss is a drawdown.
- Every simulation takes a ``seed`` and is reproducible: the same inputs and seed give identical output.
- Empty input (a strategy that never traded) has no drawdown: the simulations return zeros.

Every invalid argument raises ``ValueError`` with a message naming the argument.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "block_bootstrap_drawdowns",
    "bootstrap_trade_drawdowns",
    "degrade_execution",
    "max_drawdown",
    "percentiles",
    "shuffled_trade_drawdowns",
    "stationary_bootstrap_indices",
]


def _int_arg(name: str, value, minimum: int) -> int:
    """``value`` as a plain int, or ValueError if it isn't an integer >= ``minimum`` (bools are rejected)."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return int(value)


def _returns(name: str, values) -> np.ndarray:
    """1-D float64 copy of ``values``; ValueError unless every value is finite and >= -1."""
    r = np.array(values, dtype=float)
    if r.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {r.shape}")
    if not np.all(np.isfinite(r)):
        raise ValueError(f"{name} must be finite (no NaN or inf)")
    if np.any(r < -1.0):
        raise ValueError(f"{name} must be >= -1 (a loss can't exceed 100%), got min {r.min()}")
    return r


def _check_mean_block(mean_block) -> None:
    # Written as `not >=` so NaN is rejected too. inf is allowed: one block, i.e. a random circular shift.
    if not mean_block >= 1:
        raise ValueError(f"mean_block must be >= 1, got {mean_block}")


def _drawdown(r: np.ndarray) -> float:
    """Max drawdown of already-validated returns."""
    equity = np.cumprod(np.concatenate(([1.0], 1.0 + r)))
    peak = np.maximum.accumulate(equity)  # >= 1.0, so the division is safe
    return float(np.min(equity / peak - 1.0))


def max_drawdown(r) -> float:
    """Largest peak-to-trough fall of the equity curve ``cumprod(1 + r)`` started at 1.0, as a fraction <= 0.

    The start counts as a peak. Returns 0.0 for empty or never-falling input and -1.0 if equity reaches 0.
    """
    return _drawdown(_returns("r", r))


def shuffled_trade_drawdowns(trade_returns, n_sims: int = 5000, seed=0) -> np.ndarray:
    """Max drawdown of ``n_sims`` random reorderings of the trades (each trade used exactly once).

    Every reordering ends at the same final equity; only the path, and so the drawdown, changes.
    Returns float64 of shape ``(n_sims,)``.
    """
    tr = _returns("trade_returns", trade_returns)
    n_sims = _int_arg("n_sims", n_sims, 1)
    rng = np.random.default_rng(seed)
    return np.array([_drawdown(rng.permutation(tr)) for _ in range(n_sims)])


def bootstrap_trade_drawdowns(trade_returns, n_sims: int = 5000, seed=0) -> np.ndarray:
    """Max drawdown of ``n_sims`` resamples of the trades *with replacement* (same number of trades).

    Unlike the shuffle, a bad trade can repeat, so this explores losing streaks the history didn't contain.
    Returns float64 of shape ``(n_sims,)``.
    """
    tr = _returns("trade_returns", trade_returns)
    n_sims = _int_arg("n_sims", n_sims, 1)
    rng = np.random.default_rng(seed)
    return np.array([_drawdown(rng.choice(tr, size=tr.size, replace=True)) for _ in range(n_sims)])


def stationary_bootstrap_indices(n: int, mean_block: float, rng) -> np.ndarray:
    """One stationary-bootstrap resample (Politis & Romano 1994) of the positions ``0 .. n-1``.

    Blocks of consecutive positions, wrapping from ``n - 1`` to 0: position ``t`` starts a new block at a uniformly
    random index with probability ``1 / mean_block`` (always at ``t = 0``), otherwise it is the previous index + 1
    (mod ``n``). Block lengths are geometric with mean ``mean_block``; ``mean_block=1`` is the iid bootstrap.

    ``rng`` is a ``np.random.Generator`` (advanced in place) or a seed. Returns int64 of shape ``(n,)``.
    Raises ValueError if ``n < 1`` or ``mean_block < 1`` (or NaN).
    """
    n = _int_arg("n", n, 1)
    _check_mean_block(mean_block)
    rng = np.random.default_rng(rng)
    restart = rng.random(n) < 1.0 / mean_block
    restart[0] = True
    block_id = np.cumsum(restart) - 1
    block_first_pos = np.flatnonzero(restart)
    block_start_idx = rng.integers(0, n, size=block_first_pos.size)
    offset = np.arange(n) - block_first_pos[block_id]
    return (block_start_idx[block_id] + offset) % n


def block_bootstrap_drawdowns(returns, mean_block: float = 20, n_sims: int = 2000, seed=0) -> np.ndarray:
    """Max drawdown of ``n_sims`` stationary block bootstraps of a per-period return series.

    Resampling blocks (mean length ``mean_block`` periods) keeps volatility clusters and short-range dependence that
    a trade shuffle destroys. Returns float64 of shape ``(n_sims,)``.
    """
    r = _returns("returns", returns)
    _check_mean_block(mean_block)
    n_sims = _int_arg("n_sims", n_sims, 1)
    if r.size == 0:
        return np.zeros(n_sims)
    rng = np.random.default_rng(seed)
    return np.array(
        [_drawdown(r[stationary_bootstrap_indices(r.size, mean_block, rng)]) for _ in range(n_sims)]
    )


def degrade_execution(
    returns, turnover, extra_cost_bps: float = 10.0, n_sims: int = 1000, seed=0
) -> np.ndarray:
    """Total compounded return of ``n_sims`` runs with worse execution than the backtest assumed.

    Each period ``t`` of each run pays an extra cost ``turnover[t] * u * extra_cost_bps / 1e4`` with ``u`` drawn
    independently per period and run from Uniform(0, 2): on average ``extra_cost_bps`` per unit of turnover. So
    ``1 + r'[t] = (1 + returns[t]) * (1 - extra[t])`` and each total is ``prod(1 + r') - 1``. Extra costs are never
    negative, so no run beats ``prod(1 + returns) - 1``; with zero turnover every run equals it exactly.

    ``turnover`` is traded notional / portfolio value per period (the backtest result column). Returns float64 of
    shape ``(n_sims,)``. Raises ValueError for mismatched lengths, invalid returns, negative or non-finite turnover
    or ``extra_cost_bps``, or an extra cost that could exceed 100% of the portfolio in one period.
    """
    r = _returns("returns", returns)
    to = np.array(turnover, dtype=float)
    if to.shape != r.shape:
        raise ValueError(f"turnover must have the same shape as returns {r.shape}, got {to.shape}")
    if not np.all(np.isfinite(to)) or np.any(to < 0):
        raise ValueError("turnover must be finite and >= 0")
    if not (np.isfinite(extra_cost_bps) and extra_cost_bps >= 0):
        raise ValueError(f"extra_cost_bps must be finite and >= 0, got {extra_cost_bps}")
    max_extra = 2.0 * extra_cost_bps / 1e4 * to.max(initial=0.0)
    if max_extra > 1.0:
        raise ValueError(
            f"extra cost could reach {max_extra:.3g} of the portfolio in one period (must be <= 1)"
        )
    n_sims = _int_arg("n_sims", n_sims, 1)

    rng = np.random.default_rng(seed)
    wealth = np.ones(n_sims)
    for growth, period_turnover in zip(1.0 + r, to, strict=True):
        extra = rng.uniform(0.0, 2.0, size=n_sims) * (extra_cost_bps / 1e4) * period_turnover
        wealth *= growth * (1.0 - extra)
    return wealth - 1.0


def percentiles(values, qs=(5, 50, 95)) -> dict[str, float]:
    """``{"p<q>": q-th percentile of values}`` for each ``q`` in ``qs`` (numpy's linear interpolation).

    Summarises a simulation's output, e.g. ``percentiles(block_bootstrap_drawdowns(r), (5,))["p5"]`` is the
    5th-percentile (worst 5%) drawdown. Raises ValueError for empty or non-finite ``values`` or a ``q``
    outside [0, 100].
    """
    v = np.array(values, dtype=float).ravel()
    if v.size == 0 or not np.all(np.isfinite(v)):
        raise ValueError("values must be non-empty and finite")
    out = {}
    for q in qs:
        if not 0 <= q <= 100:
            raise ValueError(f"percentiles must be in [0, 100], got {q}")
        out[f"p{q}"] = float(np.percentile(v, q))
    return out
