"""Model training and honest out-of-sample evaluation for the prediction track.

Models
- :func:`make_model`: a small, heavily regularised, deterministic LightGBM (regression or binary
  classification). Small trees, a large minimum leaf, strong L2 and row/column subsampling: on noisy
  financial targets an unregularised booster memorises noise.
- :func:`fit_vol_model`: the volatility model is **anchored to EWMA**. It never forecasts volatility from
  scratch; it learns a log correction ``ln(y / ewma)`` and forecasts
  ``ewma * exp(correction + s2 / 2)``, where ``s2`` is the variance of the correction's residuals
  (log-normal bias fix: if ``ln y`` is normal with mean ``m`` and variance ``s2``, ``E[y] = exp(m + s2/2)``).
  A from-scratch model lost to EWMA in the demo; a correction on top of it starts from EWMA's skill.

Forecasters and evaluation
- A *forecaster* is ``f(X_train, y_train, X_test) -> predictions for the X_test rows``. It is handed the
  training labels and the test features only, never the test labels. :func:`column_forecaster` turns a
  baseline column (e.g. ``ewma_vol_20``) into one; :func:`estimator_forecaster` fits a fresh model per split.
- :func:`cpcv_evaluate` scores every forecaster on **identical test rows** of each combinatorial purged
  split (:func:`lab.validation.splits.cpcv`, purge = label horizon, plus an embargo), so a model and its
  baselines are always compared on the same data.
- :func:`walk_forward_predict` is the production schedule: refit every ``step`` rows on the last
  ``train_size`` rows whose labels are already known (purge = horizon), predict the next block.

Predictions of a classifier are always the probability of class 1 (:func:`predict_values`).

Metrics (empty input gives NaN metrics; a constant forecaster or a constant target gives a NaN
correlation, never a warning: TESTING.md bug #3)
- :func:`vol_metrics`: QLIKE on variances (punishes under-forecasting risk more than over-forecasting),
  MSE of log volatility, Pearson correlation.
- :func:`regression_metrics`: MSE, MAE, R^2, correlation.
- :func:`classification_metrics`: accuracy, log loss, Brier score, ROC AUC.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import rankdata

from lab.validation.splits import cpcv

__all__ = [
    "LOG_LOSS_EPS",
    "TASKS",
    "VolEstimator",
    "VolModel",
    "beat_share",
    "classification_metrics",
    "column_forecaster",
    "cpcv_evaluate",
    "estimator_forecaster",
    "fit_vol_model",
    "make_model",
    "predict_values",
    "regression_metrics",
    "vol_metrics",
    "walk_forward_predict",
]

TASKS = ("regression", "classification")

# Relative flatness, the same rule as lab.validation.stats (TESTING 5.2A): a spread this small next to
# the size of the values is round-off, not variation.
_REL_TOL = 1e-9

# Probabilities are clipped to [eps, 1 - eps] inside the log loss so a confident miss costs ~34.5, not inf.
LOG_LOSS_EPS = 1e-15

Forecaster = Callable[[pd.DataFrame, pd.Series, pd.DataFrame], Any]

# ----------------------------------------------------------------------------- models


def make_model(task: str = "regression", seed: int = 0) -> lgb.LGBMRegressor | lgb.LGBMClassifier:
    """A small, heavily regularised, deterministic LightGBM for ``task`` ("regression" or "classification").

    At most 7 leaves (depth 3), at least 50 rows per leaf, L2 = 10, learning rate 0.03, 200 trees,
    80% row subsampling every iteration and 80% of the features per tree. ``seed`` drives the
    subsampling; ``deterministic`` + row-wise histograms + one thread make a fit bit-reproducible.
    """
    if task not in TASKS:
        raise ValueError(f"task must be one of {TASKS}, got {task!r}")
    params = dict(
        n_estimators=200,
        learning_rate=0.03,
        num_leaves=7,
        max_depth=3,
        min_child_samples=50,
        reg_lambda=10.0,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        random_state=seed,
        n_jobs=1,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )
    if task == "classification":
        return lgb.LGBMClassifier(objective="binary", **params)
    return lgb.LGBMRegressor(objective="regression", **params)


def predict_values(model, X) -> np.ndarray:
    """Predictions of ``model`` for the rows of ``X`` as a float array.

    A classifier (anything with ``predict_proba``) gives the probability of class 1 (0.0 everywhere if
    it never saw class 1). When ``X`` is a DataFrame and the model records the feature names it was fit
    on (``feature_names_in_``), the columns are selected by name first: LightGBM predicts by column
    position, so a reordered frame would otherwise give silently wrong numbers.
    """
    names = getattr(model, "feature_names_in_", None)
    if isinstance(X, pd.DataFrame) and names is not None:
        X = _select(X, names)
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(X), dtype=float)
        hit = np.flatnonzero(np.asarray(model.classes_) == 1)
        return proba[:, hit[0]] if hit.size else np.zeros(len(proba))
    return np.asarray(model.predict(X), dtype=float)


@dataclass(frozen=True)
class VolModel:
    """EWMA-anchored volatility model (built by :func:`fit_vol_model`).

    ``model`` predicts the log correction ``ln(y / ewma)`` from ``features``; ``resid_var`` is the
    in-sample mean squared residual of that correction. The forecast is
    ``ewma * exp(model + resid_var / 2)``. ``anchor`` names the feature column that holds the EWMA
    forecast (None when the anchor was passed as plain values; then ``predict`` needs it explicitly).
    """

    model: lgb.LGBMRegressor
    features: tuple[str, ...]
    anchor: str | None
    resid_var: float

    def correction(self, X: pd.DataFrame) -> np.ndarray:
        """Bias-fixed log correction ``model(X) + resid_var / 2`` for each row (columns picked by name)."""
        return np.asarray(self.model.predict(_select(_frame(X), self.features)), dtype=float) + (
            self.resid_var / 2.0
        )

    def predict(self, X: pd.DataFrame, ewma_forecast=None) -> np.ndarray:
        """Volatility forecast per row of ``X``: ``ewma * exp(correction)``.

        ``ewma_forecast`` defaults to the ``anchor`` column of ``X``.
        """
        X = _frame(X)
        if ewma_forecast is None:
            if self.anchor is None:
                raise ValueError("this VolModel has no anchor column: pass ewma_forecast")
            ewma_forecast = self.anchor
        _, ewma = _anchor_values(X, ewma_forecast)
        return ewma * np.exp(self.correction(X))


def fit_vol_model(X: pd.DataFrame, y_vol, ewma_forecast, *, seed: int = 0) -> VolModel:
    """Fit the EWMA-anchored volatility model.

    ``X``: features (DataFrame, string column names; NaN allowed). ``y_vol``: realised forward volatility
    (e.g. :func:`lab.models.labels.forward_vol`), > 0 and finite. ``ewma_forecast``: the EWMA forecast for
    the same rows, > 0 and finite, given either as the name of a column of ``X`` (it becomes the
    model's ``anchor``) or as values aligned with ``X``; a Series whose name is a column of ``X`` holding
    exactly the same values also sets the anchor (e.g. :func:`lab.models.baselines.ewma_vol` with span 20
    and the ``ewma_vol_20`` feature).

    The booster (:func:`make_model`, ``seed``) learns ``z = ln(y_vol) - ln(ewma)``; the forecast is
    ``ewma * exp(z_hat + s2 / 2)`` with ``s2 = mean((z - z_hat)**2)`` on the training rows.
    """
    X = _frame(X)
    if len(X) == 0:
        raise ValueError("X has no rows")
    anchor, ewma = _anchor_values(X, ewma_forecast)
    y = _aligned_values(y_vol, X, "y_vol")
    if not (np.isfinite(y).all() and (y > 0).all()):
        raise ValueError("y_vol must be finite and > 0 on every row (drop rows without a label)")
    z = np.log(y) - np.log(ewma)
    model = make_model("regression", seed=seed).fit(X, z)
    resid = z - np.asarray(model.predict(X), dtype=float)
    return VolModel(
        model=model,
        features=tuple(X.columns),
        anchor=anchor,
        resid_var=float(np.mean(resid * resid)),
    )


class VolEstimator:
    """``fit(X, y)`` / ``predict(X)`` wrapper around :func:`fit_vol_model`, anchored on column ``anchor``.

    ``VolEstimator`` is a zero-argument factory, so it plugs into :func:`estimator_forecaster` and
    :func:`walk_forward_predict` (``make=VolEstimator``).
    """

    def __init__(self, anchor: str = "ewma_vol_20", seed: int = 0) -> None:
        self.anchor = anchor
        self.seed = seed

    def fit(self, X: pd.DataFrame, y) -> VolEstimator:
        self.model_ = fit_vol_model(X, y, self.anchor, seed=self.seed)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model_.predict(X)


# ----------------------------------------------------------------------------- metrics


def vol_metrics(y, yhat) -> dict[str, float]:
    """Volatility forecast quality. ``y`` realised, ``yhat`` forecast volatility (same units), both > 0.

    - ``qlike``: mean of ``u - ln(u) - 1`` with ``u = y**2 / yhat**2`` (Patton's QLIKE on variances).
      0 only for a perfect forecast. Under-forecasting by a factor ``k`` costs more than over-forecasting
      by the same factor: ``k**2 - 1/k**2 > 2 ln(k**2)`` for ``k > 1``.
    - ``mse_log``: mean of ``(ln yhat - ln y)**2`` (symmetric in the log).
    - ``corr``: Pearson correlation of ``y`` and ``yhat``; NaN when either is constant or n < 2.

    Empty input gives NaN for all three.
    """
    y, yhat = _pair(y, yhat)
    if len(y) == 0:
        return {"qlike": np.nan, "mse_log": np.nan, "corr": np.nan}
    if (y <= 0).any() or (yhat <= 0).any():
        raise ValueError("volatilities must be > 0")
    log_ratio = np.log(y / yhat)
    # u - 1 - ln(u) >= 0 for every u > 0; the clip only removes round-off of order 1e-32 next to u == 1.
    qlike = np.maximum((y / yhat) ** 2 - 1.0 - 2.0 * log_ratio, 0.0)
    return {
        "qlike": float(qlike.mean()),
        "mse_log": float(np.mean(log_ratio * log_ratio)),
        "corr": _corr(y, yhat),
    }


def regression_metrics(y, yhat) -> dict[str, float]:
    """``mse``, ``mae``, ``r2`` (1 - SSE/SST; NaN when ``y`` is constant) and ``corr`` (Pearson; NaN when
    either side is constant or n < 2). Empty input gives NaN for all four."""
    y, yhat = _pair(y, yhat)
    if len(y) == 0:
        return {"mse": np.nan, "mae": np.nan, "r2": np.nan, "corr": np.nan}
    err = yhat - y
    sse = float(np.sum(err * err))
    dev = y - y.mean()
    sst = float(np.sum(dev * dev))
    flat = _standardise(y) is None
    return {
        "mse": sse / len(y),
        "mae": float(np.mean(np.abs(err))),
        "r2": np.nan if flat else 1.0 - sse / sst,
        "corr": _corr(y, yhat),
    }


def classification_metrics(y, p) -> dict[str, float]:
    """Binary classification quality. ``y`` in {0, 1}; ``p`` = forecast probability of class 1, in [0, 1].

    - ``accuracy``: share of rows where ``(p >= 0.5) == y``.
    - ``log_loss``: mean negative log-likelihood, probabilities clipped to ``[LOG_LOSS_EPS, 1 - LOG_LOSS_EPS]``.
    - ``brier``: mean of ``(p - y)**2``.
    - ``auc``: ROC AUC (Mann-Whitney, ties count half); NaN when only one class is present.

    Empty input gives NaN for all four.
    """
    y, p = _pair(y, p)
    if len(y) == 0:
        return {"accuracy": np.nan, "log_loss": np.nan, "brier": np.nan, "auc": np.nan}
    if not np.isin(y, (0.0, 1.0)).all():
        raise ValueError("classification labels must be 0 or 1")
    if (p < 0).any() or (p > 1).any():
        raise ValueError("probabilities must lie in [0, 1]")
    pc = np.clip(p, LOG_LOSS_EPS, 1.0 - LOG_LOSS_EPS)
    pos = y == 1.0
    n_pos = int(pos.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        auc = np.nan
    else:
        ranks = rankdata(p)  # average ranks for ties
        auc = (float(ranks[pos].sum()) - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return {
        "accuracy": float(np.mean((p >= 0.5) == pos)),
        "log_loss": float(-np.mean(np.where(pos, np.log(pc), np.log1p(-pc)))),
        "brier": float(np.mean((p - y) ** 2)),
        "auc": auc,
    }


# ----------------------------------------------------------------------------- forecasters


def column_forecaster(column: str) -> Forecaster:
    """A baseline forecaster that reads ``column`` of the test features (e.g. ``"ewma_vol_20"``)."""

    def forecast(X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame) -> np.ndarray:
        return _select(X_test, [column]).iloc[:, 0].to_numpy(dtype=float)

    return forecast


def estimator_forecaster(make: Callable[[], Any] = make_model) -> Forecaster:
    """A forecaster that fits ``make()`` on each split's training rows and predicts its test rows
    (:func:`predict_values`: classifiers give the probability of class 1)."""

    def forecast(X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame) -> np.ndarray:
        return predict_values(make().fit(X_train, y_train), X_test)

    return forecast


def cpcv_evaluate(
    X: pd.DataFrame,
    y,
    forecasters: Mapping[str, Forecaster],
    n_groups: int = 6,
    n_test_groups: int = 2,
    *,
    horizon: int,
    embargo: int,
    metrics: Callable[[np.ndarray, np.ndarray], Mapping[str, float]] = vol_metrics,
) -> pd.DataFrame:
    """Score every forecaster on identical test rows of every CPCV split.

    Rows of ``X`` / ``y`` are time-ordered bars (index strictly increasing; ``y`` finite on every row:
    drop warm-up and label-less rows first). Splits come from
    ``lab.validation.splits.cpcv(len(X), n_groups, n_test_groups, horizon=horizon, embargo=embargo)``:
    ``horizon`` is the label horizon (purge) and ``embargo`` the rows dropped after each test group.
    Each forecaster is called as ``f(X_train, y_train, X_test)`` and must return one finite prediction
    per test row; ``metrics(y_test, predictions)`` scores it (default :func:`vol_metrics`).

    Returns one row per (split, forecaster), in split order then ``forecasters`` order, with columns
    ``split, test_groups, forecaster, n_train, n_test`` followed by the metric keys.
    """
    X = _frame(X)
    if not forecasters:
        raise ValueError("forecasters is empty")
    if not (X.index.is_monotonic_increasing and X.index.is_unique):
        raise ValueError("X index must be strictly increasing (time-ordered rows)")
    y_values = _aligned_values(y, X, "y")
    if not np.isfinite(y_values).all():
        raise ValueError("y must be finite on every row (drop warm-up and label-less rows first)")
    y_series = pd.Series(y_values, index=X.index, name=getattr(y, "name", None))
    rows = []
    for split, (train_idx, test_idx, test_groups) in enumerate(
        cpcv(len(X), n_groups, n_test_groups, horizon=horizon, embargo=embargo)
    ):
        X_train, y_train = X.iloc[train_idx], y_series.iloc[train_idx]
        X_test, y_test = X.iloc[test_idx], y_values[test_idx]
        for name, forecast in forecasters.items():
            pred = np.asarray(forecast(X_train, y_train, X_test), dtype=float)
            if pred.shape != (len(test_idx),):
                raise ValueError(
                    f"forecaster {name!r} returned shape {pred.shape} on split {split}, "
                    f"expected ({len(test_idx)},): one prediction per test row"
                )
            if not np.isfinite(pred).all():
                raise ValueError(f"forecaster {name!r} returned NaN or inf on split {split}")
            rows.append(
                {
                    "split": split,
                    "test_groups": test_groups,
                    "forecaster": name,
                    "n_train": len(train_idx),
                    "n_test": len(test_idx),
                    **metrics(y_test, pred),
                }
            )
    return pd.DataFrame(rows)


def beat_share(
    results: pd.DataFrame, model: str, baseline: str, metric: str = "qlike", lower_is_better: bool = True
) -> float:
    """Share of the splits in ``cpcv_evaluate`` output where ``model`` strictly beats ``baseline`` on
    ``metric``. A tie or a NaN on either side counts as not beating (the conservative reading)."""
    for name in (model, baseline):
        if name not in set(results["forecaster"]):
            raise ValueError(f"forecaster {name!r} is not in the results")
    table = results.pivot(index="split", columns="forecaster", values=metric)
    m, b = table[model].to_numpy(dtype=float), table[baseline].to_numpy(dtype=float)
    wins = m < b if lower_is_better else m > b  # NaN compares False: not a win
    return float(np.mean(wins))


def walk_forward_predict(
    X: pd.DataFrame,
    y,
    train_size: int,
    step: int,
    horizon: int,
    make: Callable[[], Any] = make_model,
) -> pd.Series:
    """Production-style out-of-sample predictions: refit every ``step`` rows, predict the next block.

    Block ``k`` covers rows ``T .. T + step - 1`` with ``T = train_size + horizon + k * step`` (the last
    block may be shorter, so every row from the first ``T`` on gets a prediction). Its model is
    ``make()`` fit on rows ``T - horizon - train_size .. T - horizon - 1``: purge = ``horizon``, so the
    newest training label (row ``T - horizon - 1``, window up to bar ``T - 1``) is complete before the
    block starts and no label overlaps a prediction time. Training rows with a missing (NaN) label are
    skipped; prediction rows may have NaN labels (the future is unknown). Classifiers give the
    probability of class 1. Rows before the first block are NaN.

    Returns a float Series named ``"prediction"`` on ``X.index``.
    """
    X = _frame(X)
    train_size = _int_arg("train_size", train_size, 1)
    step = _int_arg("step", step, 1)
    horizon = _int_arg("horizon", horizon, 0)
    y_values = _aligned_values(y, X, "y")
    n = len(X)
    first = train_size + horizon
    if n <= first:
        raise ValueError(
            f"need more than train_size + horizon = {first} rows to make a prediction, got {n}"
        )
    y_series = pd.Series(y_values, index=X.index, name=getattr(y, "name", None))
    out = np.full(n, np.nan)
    for start in range(first, n, step):
        train = np.arange(start - horizon - train_size, start - horizon)
        train = train[np.isfinite(y_values[train])]
        if train.size == 0:
            raise ValueError(f"no labelled training rows for the block starting at row {start}")
        test = np.arange(start, min(start + step, n))
        model = make().fit(X.iloc[train], y_series.iloc[train])
        pred = predict_values(model, X.iloc[test])
        out[test] = pred
    return pd.Series(out, index=X.index, name="prediction")


# ----------------------------------------------------------------------------- helpers


def _int_arg(name: str, value, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer) or value < minimum:
        raise ValueError(f"{name} must be an int >= {minimum}, got {value!r}")
    return int(value)


def _frame(X) -> pd.DataFrame:
    if not isinstance(X, pd.DataFrame):
        raise ValueError(f"X must be a pandas DataFrame of features, got {type(X).__name__}")
    return X


def _select(X: pd.DataFrame, names: Sequence[str]) -> pd.DataFrame:
    """Columns ``names`` of ``X`` in that order; ValueError naming any that are missing."""
    names = list(names)
    missing = [c for c in names if c not in X.columns]
    if missing:
        raise ValueError(f"X is missing feature columns: {missing}")
    return X.loc[:, names]


def _aligned_values(v, X: pd.DataFrame, name: str) -> np.ndarray:
    """``v`` as a 1-D float array with one value per row of ``X`` (a Series must share ``X.index``)."""
    if isinstance(v, pd.Series) and not v.index.equals(X.index):
        raise ValueError(f"{name} index must equal X.index")
    a = np.asarray(v, dtype=float)
    if a.shape != (len(X),):
        raise ValueError(f"{name} must be 1-D with one value per row of X ({len(X)}), got shape {a.shape}")
    return a


def _anchor_values(X: pd.DataFrame, ewma_forecast) -> tuple[str | None, np.ndarray]:
    """(anchor column name or None, EWMA values > 0) for ``fit_vol_model`` / ``VolModel.predict``."""
    if isinstance(ewma_forecast, str):
        anchor = ewma_forecast
        ewma = _select(X, [anchor]).iloc[:, 0].to_numpy(dtype=float)
    else:
        ewma = _aligned_values(ewma_forecast, X, "ewma_forecast")
        name = getattr(ewma_forecast, "name", None)
        same = isinstance(name, str) and name in X.columns and np.array_equal(X[name].to_numpy(float), ewma)
        anchor = name if same else None
    if not (np.isfinite(ewma).all() and (ewma > 0).all()):
        raise ValueError("the EWMA forecast must be finite and > 0 on every row")
    return anchor, ewma


def _pair(a, b) -> tuple[np.ndarray, np.ndarray]:
    """Two 1-D finite float arrays of equal length."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.ndim != 1 or b.ndim != 1:
        raise ValueError("targets and forecasts must be 1-D")
    if len(a) != len(b):
        raise ValueError(f"targets and forecasts differ in length: {len(a)} != {len(b)}")
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        raise ValueError("targets and forecasts must be finite (no NaN or inf)")
    return a, b


def _standardise(x: np.ndarray) -> np.ndarray | None:
    """``(x - mean) / sd`` (population sd), or None when ``x`` has no real variation (relative flatness,
    judged in unit scale so tiny or huge values neither underflow nor overflow)."""
    scale = float(np.max(np.abs(x)))
    u = x / scale if scale > 0 else x
    d = u - u.mean()
    sd = float(np.sqrt(np.mean(d * d)))
    if sd <= _REL_TOL:  # u has max |u| == 1 (or is all zeros)
        return None
    return d / sd


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation in [-1, 1]; NaN for fewer than 2 values or a constant side."""
    if len(a) < 2:
        return np.nan
    za, zb = _standardise(a), _standardise(b)
    if za is None or zb is None:
        return np.nan
    return float(np.clip(np.mean(za * zb), -1.0, 1.0))
