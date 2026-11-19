"""Starter end-to-end model tests (osprey names: compute_features, FEATURES, bars-based labels and baselines;
vol labels and baselines are per bar, not annualised). The starter's test_online_buffer_matches_batch_features
is superseded by tests/test_features_leakage.py's bit-exact live-parity tests on every bar."""

import numpy as np
import pandas as pd
import pytest

from lab.data.synthetic import synthetic_market
from lab.models import baselines, labels
from lab.models.artifact import save_model, train_final
from lab.models.features import FEATURES
from lab.models.features import compute_features as build_features
from lab.models.online import ModelPredictor
from lab.models.train import cpcv_evaluate, walk_forward_predict

FEATURE_COLUMNS = list(FEATURES)


@pytest.fixture(scope="module")
def btc():
    return synthetic_market(1200, seed=11)["BTC"]


def test_features_have_no_look_ahead(btc):
    f1 = build_features(btc)
    tampered = btc.copy()
    tampered.iloc[800:] *= 3.0  # change the future
    f2 = build_features(tampered)
    pd.testing.assert_frame_equal(f1.iloc[:800], f2.iloc[:800])


def test_forward_vol_label_matches_manual(btc):
    h = 5
    y = labels.forward_vol(btc, h)
    lr = np.log(btc["close"]).diff()
    t = 300
    manual = lr.iloc[t + 1 : t + 1 + h].std()  # per bar
    assert y.iloc[t] == pytest.approx(manual)
    assert y.iloc[-h:].isna().all()


def test_cpcv_evaluate_runs_and_model_beats_naive_on_garch_data(btc):
    X = build_features(btc)
    y = labels.forward_vol(btc, 5)
    res = cpcv_evaluate(
        X, y, "vol", horizon=5,
        baselines={"naive": baselines.naive_vol(btc, 5)},
        n_groups=5, n_test_groups=2,
    )
    means = res.groupby("forecaster")["rmse_log"].mean()
    assert set(means.index) == {"model", "naive"}
    assert means["model"] < means["naive"]  # synthetic data has real vol clustering


def test_walk_forward_predict_never_uses_future_labels(btc):
    X = build_features(btc)
    y = labels.forward_vol(btc, 5)
    p1 = walk_forward_predict(X, y, "vol", horizon=5, min_train=400, retrain_every=120)
    y2 = y.copy()
    y2.iloc[900:] = y2.iloc[900:] * 10  # corrupt labels after bar 900
    p2 = walk_forward_predict(X, y2, "vol", horizon=5, min_train=400, retrain_every=120)
    # predictions for blocks trained before bar 900 must be identical
    cutoff = p1.index[900 - 5]
    pd.testing.assert_series_equal(p1.loc[:cutoff], p2.loc[:cutoff])


def test_artifact_roundtrip_and_predictor(btc, tmp_path):
    X = build_features(btc)
    y = labels.forward_vol(btc, 5)
    model, Xa = train_final("vol", X, y)
    save_model(model, tmp_path, kind="vol", target=y.name, horizon=5, features=FEATURE_COLUMNS,
               train_start=Xa.index[0], train_end=Xa.index[-1], data_snapshot="synthetic-test")
    pred = ModelPredictor(str(tmp_path)).predict(X.iloc[-1])
    assert 0 < pred < 5
