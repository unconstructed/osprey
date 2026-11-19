"""Model training and evaluation: honest comparisons, no leakage, reproducibility.

Starter tests; edits are osprey names only (bars-based labels, per-bar vol units)."""

import numpy as np
import pandas as pd
import pytest

from lab.models import labels
from lab.models.train import (
    _aligned,
    class_metrics,
    cpcv_evaluate,
    regression_metrics,
    summarize,
    vol_metrics,
    walk_forward_predict,
)

# ---------- metric known answers ----------

def test_vol_metrics_perfect_and_biased():
    t = np.array([0.3, 0.5, 0.8, 1.2])
    perfect = vol_metrics(t, t)
    assert perfect["rmse_log"] == pytest.approx(0) and perfect["qlike"] == pytest.approx(0)
    assert perfect["corr_log"] == pytest.approx(1)
    low, high = vol_metrics(t, t * 0.8), vol_metrics(t, t * 1.25)
    assert low["qlike"] > high["qlike"] > 0  # QLIKE punishes under-forecasting risk more
    assert low["rmse_log"] == pytest.approx(high["rmse_log"])


def test_vol_metrics_ignore_invalid_rows():
    t = np.array([0.3, np.nan, 0.8, 0.0, 1.0])
    p = np.array([0.3, 0.4, 0.8, 0.5, -1.0])
    m = vol_metrics(t, p)
    assert m["rmse_log"] == pytest.approx(0)


def test_metrics_handle_constant_and_empty_inputs():
    m = vol_metrics([0.3, 0.5, 0.8], [0.5, 0.5, 0.5])  # flat forecaster: no correlation, no warning
    assert np.isnan(m["corr_log"]) and np.isfinite(m["qlike"])
    assert all(np.isnan(v) for v in vol_metrics([np.nan], [0.5]).values())
    assert np.isnan(regression_metrics([1, 2, 3], [5, 5, 5])["ic"])
    assert all(np.isnan(v) for v in regression_metrics([np.nan], [1.0]).values())


def test_class_and_regression_metrics():
    assert class_metrics([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])["auc"] == 1.0
    assert class_metrics([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1])["auc"] == 0.0
    assert np.isnan(class_metrics([1, 1, 1], [0.2, 0.3, 0.4])["auc"])
    r = regression_metrics([1, 2, 3, 4], [10, 20, 30, 40])
    assert r["ic"] == pytest.approx(1.0)


# ---------- CPCV evaluation ----------

@pytest.fixture(scope="module")
def vol_data(btc, features):
    return features, labels.forward_vol(btc, 10)


def test_cpcv_rows_and_identical_test_sets(vol_data):
    X, y = vol_data
    oracle = y.copy()  # a baseline that IS the truth must score perfectly on every split
    res = cpcv_evaluate(X, y, "vol", horizon=10, baselines={"oracle": oracle, "flat": pd.Series(0.5 / np.sqrt(365), index=X.index)},
                        n_groups=5, n_test_groups=2)
    assert len(res) == 10 * 3
    o = res[res.forecaster == "oracle"]
    assert np.allclose(o["rmse_log"], 0) and np.allclose(o["qlike"], 0)
    s = summarize(res)
    assert {"qlike_mean", "qlike_std"} <= set(s.columns)
    assert s.loc["oracle", "qlike_mean"] < s.loc["model", "qlike_mean"] < s.loc["flat", "qlike_mean"]


def test_cpcv_classification_and_regression_paths(btc, features):
    yc = labels.forward_regime(btc, 20)
    rc = cpcv_evaluate(features, yc, "classification", horizon=20, n_groups=4, n_test_groups=1)
    assert rc["auc"].between(0, 1).all()
    yr = labels.forward_return(btc, 5)
    rr = cpcv_evaluate(features, yr, "regression", horizon=5, n_groups=4, n_test_groups=1)
    assert rr["ic"].between(-1, 1).all()


def test_cpcv_is_reproducible(vol_data):
    X, y = vol_data
    a = cpcv_evaluate(X, y, "vol", horizon=10, n_groups=4, n_test_groups=1, seed=3)
    b = cpcv_evaluate(X, y, "vol", horizon=10, n_groups=4, n_test_groups=1, seed=3)
    pd.testing.assert_frame_equal(a, b)


def test_aligned_drops_warmup_and_missing_labels(vol_data):
    X, y = vol_data
    Xa, ya = _aligned(X, y)
    assert not Xa.isna().any().any() and not ya.isna().any()
    assert (ya > 0).all()
    assert Xa.index[0] == X.dropna().index[0]


# ---------- walk-forward predictions ----------

@pytest.mark.parametrize("cut", [600, 900, 1200])
def test_walk_forward_predictions_cannot_see_future_labels(vol_data, cut):
    X, y = vol_data
    base = walk_forward_predict(X, y, "vol", horizon=10, min_train=400, retrain_every=100)
    corrupted = y.copy()
    # Corrupt every label not fully known by `cut`: the label at row i covers bars i+1..i+10, so rows from
    # cut - 10 on (merge check: corrupting only rows >= cut let a walk-forward without the horizon purge pass).
    corrupted.iloc[cut - 10 :] = corrupted.iloc[cut - 10 :] * 7
    p2 = walk_forward_predict(X, corrupted, "vol", horizon=10, min_train=400, retrain_every=100)
    # a block starting at b trains on labels with index < b - horizon, which end before b
    safe_until = X.index[cut]  # any block starting at or before `cut` only saw labels known by then
    blocks_ok = base.index <= safe_until
    pd.testing.assert_series_equal(base[blocks_ok], p2[blocks_ok])


def test_walk_forward_predictions_cannot_see_future_features(btc, features, vol_data):
    X, y = vol_data
    base = walk_forward_predict(X, y, "vol", horizon=10, min_train=400, retrain_every=100)
    X2 = X.copy()
    X2.iloc[1100:] = X2.iloc[1100:] * 3
    p2 = walk_forward_predict(X2, y, "vol", horizon=10, min_train=400, retrain_every=100)
    pd.testing.assert_series_equal(base.iloc[:1100], p2.iloc[:1100])


def test_walk_forward_predictions_shape_and_positivity(vol_data):
    X, y = vol_data
    p = walk_forward_predict(X, y, "vol", horizon=10, min_train=400, retrain_every=100)
    first = p.first_valid_index()
    assert p.loc[:first].iloc[:-1].isna().all()
    assert (p.dropna() > 0).all()
    assert p.loc[first:].notna().all()  # once started, every later bar gets a forecast
    pd.testing.assert_series_equal(p, walk_forward_predict(X, y, "vol", horizon=10, min_train=400, retrain_every=100))


def test_walk_forward_waits_until_enough_labels_are_known(btc, features):
    """With a long label horizon, the first blocks don't have enough finished labels to
    train on, so they are skipped rather than trained on a tiny sample."""
    y = labels.forward_vol(btc, 60)
    short = walk_forward_predict(features, y, "vol", horizon=5, min_train=200, retrain_every=50)
    long_ = walk_forward_predict(features, y, "vol", horizon=150, min_train=200, retrain_every=50)
    assert long_.first_valid_index() > short.first_valid_index()
