"""Training and honest evaluation of prediction models.

- `cpcv_evaluate`: combinatorial purged cross-validation; model vs. baselines on the
  exact same test rows, one result row per split (a distribution, not one number).
- `walk_forward_predict`: production-style out-of-sample predictions for backtests.
  The model is retrained on a schedule using only data available at the time, exactly
  like it would be in production. These predictions are what strategies consume.

Kinds:
  "vol"            EWMA-anchored regression on log(volatility / EWMA) (AnchoredVolModel);
                   predictions returned as volatility, per bar like the labels
  "regression"     plain regression
  "classification" probability of class 1
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st
from sklearn.metrics import roc_auc_score

from ..validation.splits import cpcv


def make_model(kind: str, seed: int = 0):
    import lightgbm as lgb

    # Deliberately small and heavily regularized: financial targets are noisy, and a
    # model that chases noise loses to simple baselines (see reports/demo).
    params = dict(
        n_estimators=150,
        learning_rate=0.02,
        num_leaves=7,
        min_child_samples=200,
        subsample=0.7,
        subsample_freq=1,
        colsample_bytree=0.7,
        reg_lambda=10.0,
        random_state=seed,
        n_jobs=1,
        verbose=-1,
    )
    return lgb.LGBMClassifier(**params) if kind == "classification" else lgb.LGBMRegressor(**params)


# ---------- metrics ----------

def _corr(a, b, rank=False) -> float:
    """Correlation, or NaN when either side is constant (a flat forecaster has no ranking skill)."""
    if len(a) < 2 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return float("nan")
    return float(st.spearmanr(a, b).statistic) if rank else float(np.corrcoef(a, b)[0, 1])


def vol_metrics(true_vol, pred_vol) -> dict:
    t, p = np.asarray(true_vol, float), np.asarray(pred_vol, float)
    m = np.isfinite(t) & np.isfinite(p) & (t > 0) & (p > 0)
    t, p = t[m], p[m]
    if len(t) == 0:
        return {"rmse_log": float("nan"), "corr_log": float("nan"), "qlike": float("nan")}
    lt, lp = np.log(t), np.log(p)
    ratio = t**2 / p**2
    return {
        "rmse_log": float(np.sqrt(np.mean((lt - lp) ** 2))),
        "corr_log": _corr(lt, lp),
        "qlike": float(np.mean(ratio - np.log(ratio) - 1)),  # lower is better
    }


def class_metrics(true, score) -> dict:
    t, s = np.asarray(true, float), np.asarray(score, float)
    m = np.isfinite(t) & np.isfinite(s)
    if len(np.unique(t[m])) < 2:
        return {"auc": float("nan")}
    return {"auc": float(roc_auc_score(t[m], s[m]))}


def regression_metrics(true, pred) -> dict:
    t, p = np.asarray(true, float), np.asarray(pred, float)
    m = np.isfinite(t) & np.isfinite(p)
    if not m.any():
        return {"ic": float("nan"), "rmse": float("nan")}
    return {"ic": _corr(t[m], p[m], rank=True), "rmse": float(np.sqrt(np.mean((t[m] - p[m]) ** 2)))}


METRICS = {"vol": vol_metrics, "classification": class_metrics, "regression": regression_metrics}


# ---------- fitting ----------

VOL_ANCHOR = "ewma_vol_20"  # the EWMA feature in lab.models.features (per-bar, like the vol labels)


class AnchoredVolModel:
    """The volatility model: a correction on top of the EWMA baseline, used for validation AND deployment.

    Learns target = log(true / EWMA), so the model starts from a strong baseline instead of from scratch,
    and removes the log-normal bias with the training residual variance:
    forecast = EWMA * exp(correction + resid_var / 2). ``cpcv_evaluate``, ``walk_forward_predict``,
    ``artifact.train_final`` and ``online.ModelPredictor`` all go through this one class, so the saved model
    is exactly the model that was validated.
    """

    def __init__(self, seed: int = 0, anchor: str = VOL_ANCHOR):
        self.model = make_model("vol", seed)
        self.anchor = anchor
        self.resid_var = float("nan")

    def fit(self, X: pd.DataFrame, y) -> AnchoredVolModel:
        z = np.log(np.asarray(y, float) / X[self.anchor].to_numpy())
        self.model.fit(X, z)
        self.resid_var = float(np.var(z - self.model.predict(X)))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X[self.anchor].to_numpy() * np.exp(self.model.predict(X) + 0.5 * self.resid_var)


def _fit_predict(kind: str, X_train, y_train, X_test, seed: int) -> np.ndarray:
    if kind == "vol":
        return AnchoredVolModel(seed).fit(X_train, y_train).predict(X_test)
    model = make_model(kind, seed)
    model.fit(X_train, y_train)
    if kind == "classification":
        return model.predict_proba(X_test)[:, 1]
    return model.predict(X_test)


def _aligned(X: pd.DataFrame, y: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    ok = y.notna() & np.isfinite(y)
    if "vol" in str(y.name):
        ok &= y > 0
    first_full = X.notna().all(axis=1).idxmax()  # skip warm-up rows
    ok &= X.index >= first_full
    return X.loc[ok], y.loc[ok]


def cpcv_evaluate(
    X: pd.DataFrame,
    y: pd.Series,
    kind: str,
    horizon: int,
    baselines: dict[str, pd.Series] | None = None,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: int | None = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Model vs. baselines on identical purged test sets. One row per split and forecaster."""
    Xa, ya = _aligned(X, y)
    metric = METRICS[kind]
    embargo = horizon if embargo is None else embargo
    rows = []
    for s, (train_idx, test_idx, _groups) in enumerate(cpcv(len(Xa), n_groups, n_test_groups, horizon, embargo)):
        pred = _fit_predict(kind, Xa.iloc[train_idx], ya.iloc[train_idx], Xa.iloc[test_idx], seed)
        truth = ya.iloc[test_idx].to_numpy()
        rows.append({"split": s, "forecaster": "model", **metric(truth, pred)})
        for name, b in (baselines or {}).items():
            bp = b.reindex(Xa.index).iloc[test_idx].to_numpy()
            rows.append({"split": s, "forecaster": name, **metric(truth, bp)})
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    """Mean and spread of each metric per forecaster across CPCV splits."""
    metrics = [c for c in results.columns if c not in ("split", "forecaster")]
    agg = results.groupby("forecaster")[metrics].agg(["mean", "std"])
    agg.columns = [f"{m}_{a}" for m, a in agg.columns]
    return agg


def walk_forward_predict(
    X: pd.DataFrame,
    y: pd.Series,
    kind: str,
    horizon: int,
    min_train: int = 730,
    retrain_every: int = 90,
    seed: int = 0,
) -> pd.Series:
    """Out-of-sample predictions for every bar after the first `min_train` usable rows.

    At each retrain date, the model trains on rows whose labels were fully known by then
    (purged by `horizon`), then predicts the next `retrain_every` bars.
    """
    Xa, ya = _aligned(X, y)
    pos = pd.Series(np.arange(len(X)), index=X.index)
    train_pos = pos.loc[Xa.index].to_numpy()
    preds = pd.Series(np.nan, index=X.index, name=f"pred_{y.name}")
    start = train_pos[min(min_train, len(train_pos) - 1)]
    for block_start in range(start, len(X), retrain_every):
        usable = train_pos < block_start - horizon
        if usable.sum() < min_train // 2:
            continue
        block = slice(block_start, min(block_start + retrain_every, len(X)))
        preds.iloc[block] = _fit_predict(
            kind, Xa.loc[usable], ya.loc[usable], X.iloc[block], seed
        )
    return preds
