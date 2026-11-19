"""Validation statistics: Sharpe, PSR, expected max Sharpe, effective trials, DSR and PBO (CSCV).

Conventions
- Returns are simple fractional returns per period (0.01 = 1%), one value per bar.
- Every Sharpe ratio here is PER PERIOD (mean / standard deviation, ddof=1 unless stated) except
  ``annualized_sharpe``, which multiplies by sqrt(periods_per_year) (365: crypto trades every day).
- A return matrix has one row per period and one column per trial (strategy variant).
- Flat series (no real variation) have Sharpe 0. Flatness is judged RELATIVE to the series' own size
  (``_is_flat``), so no result depends on the units the returns are measured in (TESTING.md 5.2A).
- Scale-free quantities (Sharpe, PSR, correlations) are computed on the series divided by its largest
  absolute value. That changes nothing mathematically, but keeps the 2nd to 4th moments clear of float
  underflow and overflow, so results stay unit-independent across the whole float range.

References: Bailey & Lopez de Prado (2012) "The Sharpe ratio efficient frontier" (PSR); (2014) "The deflated
Sharpe ratio" (expected max Sharpe, DSR); Bailey, Borwein, Lopez de Prado & Zhu (2016) "The probability of
backtest overfitting" (CSCV, PBO).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats as _st

_REL_SD_TOL = 1e-9
EULER_GAMMA = 0.5772156649
# cscv_splits enumerates every combination and samples from the list when the cap keeps at least
# 1/_ENUMERATE_FACTOR of them; otherwise it draws random halves and rejects repeats (few repeats then).
_ENUMERATE_FACTOR = 4


def _is_flat(sd, scale):
    """No real variation: spread is negligible next to the size of the values.

    All-zero data has scale 0 and sd 0, so it counts as flat. Works elementwise on arrays.
    """
    return sd <= _REL_SD_TOL * scale


def _vector(r, name: str) -> np.ndarray:
    a = np.asarray(r, dtype=float)
    if a.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got {a.ndim}-D")
    if not np.isfinite(a).all():
        raise ValueError(f"{name} must be finite (no NaN or inf)")
    return a


def _matrix(m, name: str) -> np.ndarray:
    a = np.asarray(m, dtype=float)
    if a.ndim != 2:
        raise ValueError(f"{name} must be 2-D (rows = periods, columns = trials), got {a.ndim}-D")
    if not np.isfinite(a).all():
        raise ValueError(f"{name} must be finite (no NaN or inf)")
    return a


def _unit(r: np.ndarray) -> np.ndarray | None:
    """``r / max|r|`` (largest absolute value exactly 1), or None when every value is 0."""
    scale = np.abs(r).max()
    return r / scale if scale > 0 else None


def _unit_columns(m: np.ndarray) -> np.ndarray:
    """Each column divided by its largest absolute value; all-zero columns stay zero."""
    scale = np.abs(m).max(axis=0)
    return np.divide(m, scale, out=np.zeros_like(m), where=scale > 0)


def _column_stats(m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(mean, sd with ddof=1, flat mask) of each column in unit scale. Needs at least 2 rows."""
    x = _unit_columns(m)
    sd = x.std(axis=0, ddof=1)
    # Unit columns have max |x| == 1; all-zero columns have sd 0, which is flat at scale 1 too.
    return x.mean(axis=0), sd, _is_flat(sd, 1.0)


def sharpe(r, ddof: int = 1) -> float:
    """Per-period Sharpe ratio mean(r) / std(r, ddof). 0.0 for a flat series or fewer than 2 values."""
    if ddof not in (0, 1):
        raise ValueError(f"ddof must be 0 or 1, got {ddof!r}")
    r = _vector(r, "returns")
    if len(r) < 2:
        return 0.0
    x = _unit(r)
    if x is None:
        return 0.0
    sd = x.std(ddof=ddof)
    if _is_flat(sd, 1.0):  # x has max |x| == 1
        return 0.0
    return float(x.mean() / sd)


def annualized_sharpe(r, periods_per_year: float = 365) -> float:
    """Per-period Sharpe times sqrt(periods_per_year). Default 365: crypto trades every day."""
    if not (np.isfinite(periods_per_year) and periods_per_year > 0):
        raise ValueError(f"periods_per_year must be finite and > 0, got {periods_per_year!r}")
    return sharpe(r) * float(np.sqrt(periods_per_year))


def probabilistic_sharpe_ratio(r, sr_benchmark: float = 0.0) -> float:
    """Probability that the true per-period Sharpe exceeds ``sr_benchmark`` (PSR, Bailey & Lopez de Prado).

    PSR = Phi((SR - SR*) * sqrt(n - 1) / sqrt(var_term)) with the per-period sample SR (ddof=1),
    var_term = 1 - skew*SR + (kurt - 1)/4 * SR^2, skew and kurt the (biased) sample skewness and
    non-excess kurtosis. Returns 0.0 for a flat series and for fewer than 3 observations.
    """
    r = _vector(r, "returns")
    if not np.isfinite(sr_benchmark):
        raise ValueError(f"sr_benchmark must be finite, got {sr_benchmark!r}")
    n = len(r)
    if n < 3:
        return 0.0
    x = _unit(r)
    if x is None:
        return 0.0
    sd = x.std(ddof=1)
    if _is_flat(sd, 1.0):  # x has max |x| == 1
        return 0.0
    sr = float(x.mean() / sd)
    skew = float(_st.skew(x))
    kurt = float(_st.kurtosis(x, fisher=False))
    # TESTING.md's proof: var_term = (1 - skew*SR/2)**2 + (kurt - 1 - skew**2)*SR**2/4 >= 0 because
    # kurt >= skew**2 + 1 (Pearson's inequality), so in exact arithmetic it is never negative.
    var_term = (1 - skew * sr / 2) ** 2 + (kurt - 1 - skew**2) * sr**2 / 4
    if var_term <= 0:
        # NOT pragma'd: that proof only holds in exact arithmetic, so this line can run. Both terms are 0 for
        # a two-valued sample (kurt == 1 + skew**2 exactly) with skew * SR == 2. In floating point, var_term
        # then comes out as exactly 0.0 or rounds to either side of 0, e.g. -4.4e-16 for
        # [0.022996598285221187, 0.012996598285221187, 0.012996598285221187] (tests pin both cases).
        # The SR estimate's asymptotic variance is 0 there, so PSR is the z -> +/-inf limit of the formula:
        # 1 above the benchmark, 0 below, 0.5 at it (the same values a tiny positive var_term gives).
        return float(0.5 * (1.0 + np.sign(sr - sr_benchmark)))
    z = (sr - sr_benchmark) * np.sqrt((n - 1) / var_term)
    return float(_st.norm.cdf(z))


def expected_max_sharpe(n_trials: float, variance: float) -> float:
    """Expected maximum per-period Sharpe among ``n_trials`` skill-less trials (Bailey & Lopez de Prado).

    sqrt(V) * ((1 - g) * Phi^-1(1 - 1/N) + g * Phi^-1(1 - 1/(N e))), g = Euler-Mascheroni constant,
    V = variance of the trials' per-period Sharpe ratios. ``n_trials`` may be fractional (effective trials).
    0.0 for N <= 1 (no search). The approximation dips below 0 for 1 < N < ~1.28; the expected maximum of
    N >= 1 zero-mean trials is never below 0, so the result is floored at 0 (a negative benchmark would make
    the DSR more lenient than the plain PSR).
    """
    if not np.isfinite(n_trials):
        raise ValueError(f"n_trials must be finite, got {n_trials!r}")
    if not (np.isfinite(variance) and variance >= 0):
        raise ValueError(f"variance must be finite and >= 0, got {variance!r}")
    if n_trials <= 1:
        return 0.0
    g = EULER_GAMMA
    # isf(q) == Phi^-1(1 - q), computed without rounding 1 - q (accurate for large N).
    z = (1 - g) * _st.norm.isf(1 / n_trials) + g * _st.norm.isf(1 / (n_trials * math.e))
    return float(np.sqrt(variance) * max(float(z), 0.0))


def effective_trials(returns_matrix) -> float:
    """Effective number of independent trials: exp(entropy) of the normalised eigenvalues of the trials'
    correlation matrix (entropy effective rank). 1.0 for a single (non-flat) column, k for k uncorrelated
    columns. Flat columns carry no information and are dropped first.
    """
    m = _matrix(returns_matrix, "returns_matrix")
    if m.shape[0] < 2 or m.shape[1] < 1:
        raise ValueError(f"returns_matrix needs at least 2 rows and 1 column, got shape {m.shape}")
    _, _, flat = _column_stats(m)
    live = _unit_columns(m[:, ~flat])
    if live.shape[1] < 2:
        return 1.0
    corr = np.corrcoef(live, rowvar=False)
    eig = np.linalg.eigvalsh(corr)
    p = eig[eig > 0]  # zero eigenvalues add nothing to the entropy; drops -1e-16 rounding noise too
    p = p / p.sum()
    return float(np.exp(-np.sum(p * np.log(p))))


def deflated_sharpe_ratio(best_returns, trial_sharpes, n_trials: float | None = None) -> dict:
    """Deflated Sharpe ratio: PSR of the selected strategy against the Sharpe expected from luck alone.

    ``trial_sharpes`` are the per-period Sharpe ratios of every trial tried (their variance, ddof=1, sets the
    luck benchmark; 0.0 with a single trial). ``n_trials`` defaults to len(trial_sharpes); pass the raw count
    of every trial run, or an effective count (``effective_trials``), which may be fractional.
    Keys: dsr, best_sharpe_per_period, expected_max_sharpe, trial_sharpe_variance, n_trials.
    """
    ts = _vector(trial_sharpes, "trial_sharpes")
    if len(ts) == 0:
        raise ValueError("trial_sharpes must not be empty")
    if n_trials is None:
        n_trials = len(ts)
    elif not (np.isfinite(n_trials) and n_trials >= 1):
        raise ValueError(f"n_trials must be finite and >= 1, got {n_trials!r}")
    variance = float(np.var(ts, ddof=1)) if len(ts) > 1 else 0.0
    e_max = expected_max_sharpe(n_trials, variance)
    return {
        "dsr": probabilistic_sharpe_ratio(best_returns, sr_benchmark=e_max),
        "best_sharpe_per_period": sharpe(best_returns),
        "expected_max_sharpe": e_max,
        "trial_sharpe_variance": variance,
        "n_trials": n_trials,
    }


def _column_sharpes(m: np.ndarray) -> np.ndarray:
    if m.shape[0] < 2:
        return np.zeros(m.shape[1])
    mean, sd, flat = _column_stats(m)
    return np.divide(mean, sd, out=np.zeros(m.shape[1]), where=~flat)


def column_sharpes(m) -> np.ndarray:
    """Per-period Sharpe (ddof=1) of each column; 0.0 for a flat column (flatness judged per column, relative
    to that column's own size) and for every column when there are fewer than 2 rows."""
    return _column_sharpes(_matrix(m, "m"))


def _check_cscv(n_blocks, max_combinations) -> None:
    # bool is an int subclass: True/False are rejected by the >= 2 test (and explicitly for max_combinations).
    if not isinstance(n_blocks, (int, np.integer)) or n_blocks < 2 or n_blocks % 2:
        raise ValueError(f"n_blocks must be an even integer >= 2, got {n_blocks!r}")
    if (
        isinstance(max_combinations, bool)
        or not isinstance(max_combinations, (int, np.integer))
        or max_combinations < 1
    ):
        raise ValueError(f"max_combinations must be an integer >= 1, got {max_combinations!r}")


def cscv_splits(n_blocks: int, max_combinations: int, seed=0) -> list[tuple[int, ...]]:
    """In-sample block sets for CSCV: every half-size subset of range(n_blocks), in lexicographic order.

    If there are more than ``max_combinations`` of them (C(n, n/2)), a distinct random subset of exactly
    ``max_combinations`` (seeded), also in lexicographic order. Each set is a sorted tuple of ints.
    """
    _check_cscv(n_blocks, max_combinations)
    n_blocks, max_combinations = int(n_blocks), int(max_combinations)
    half = n_blocks // 2
    total = math.comb(n_blocks, half)
    if total <= max_combinations:
        return list(itertools.combinations(range(n_blocks), half))
    rng = np.random.default_rng(seed)
    if total <= _ENUMERATE_FACTOR * max_combinations:
        every = list(itertools.combinations(range(n_blocks), half))
        return [every[i] for i in sorted(rng.choice(total, size=max_combinations, replace=False).tolist())]
    chosen: set[tuple[int, ...]] = set()
    while len(chosen) < max_combinations:
        chosen.add(tuple(sorted(rng.choice(n_blocks, size=half, replace=False).tolist())))
    return sorted(chosen)


def pbo(returns_matrix, n_blocks: int = 16, max_combinations: int = 4000, seed=0) -> dict:
    """Probability of backtest overfitting by combinatorially symmetric cross-validation (CSCV).

    Rows are split into ``n_blocks`` contiguous blocks (``np.array_split``: sizes differ by at most 1, the first
    blocks get the extra rows). For each in-sample half from ``cscv_splits``: the trial with the best in-sample
    Sharpe gets its out-of-sample rank r among the N trials (1 = worst; OOS ties share the average rank),
    w = r / (N + 1), logit = ln(w / (1 - w)). PBO = share of logits <= 0: an IS winner that is only median out
    of sample (logit 0) counts as overfit. When several trials tie for the best in-sample Sharpe (e.g. trials
    that never trade in that half), the one with the worst out-of-sample rank is scored: conservative, and
    PBO does not depend on the order of the trial columns.
    Keys: pbo, logits (np.ndarray, one per split), n_combinations, n_trials.
    """
    _check_cscv(n_blocks, max_combinations)
    m = _matrix(returns_matrix, "returns_matrix")
    t, n = m.shape
    if n < 2:
        raise ValueError(f"returns_matrix needs at least 2 trials (columns) for PBO, got {n}")
    if t < n_blocks:
        raise ValueError(f"returns_matrix needs at least n_blocks={n_blocks} rows, got {t}")
    block_of_row = np.concatenate(
        [np.full(len(b), i) for i, b in enumerate(np.array_split(np.arange(t), n_blocks))]
    )
    combos = cscv_splits(n_blocks, max_combinations, seed)
    logits = np.empty(len(combos))
    for k, combo in enumerate(combos):
        in_sample = np.isin(block_of_row, combo)
        sr_is = _column_sharpes(m[in_sample])
        sr_oos = _column_sharpes(m[~in_sample])
        best = sr_oos[sr_is == sr_is.max()].min()  # IS ties: score the worst OOS candidate
        rank = np.sum(sr_oos < best) + (np.sum(sr_oos == best) + 1) / 2
        w = rank / (n + 1)
        logits[k] = np.log(w / (1 - w))
    return {
        "pbo": float(np.mean(logits <= 0)),
        "logits": logits,
        "n_combinations": len(combos),
        "n_trials": n,
    }
