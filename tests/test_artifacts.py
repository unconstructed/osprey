"""Model artifacts (integrity, round trips) and the live ModelPredictor.

From the starter's tests/test_artifacts_loaders.py (artifact section; its loader and synthetic-data tests are
superseded by tests/test_loaders.py and tests/test_synthetic.py). Edits: osprey names (FEATURES, bars-based
labels); the vol model is the EWMA-anchored AnchoredVolModel, so the predictor is compared with model.predict
instead of exp(model.predict) (that old assertion pinned bug #17 in TESTING.md).
"""

import json

import pytest

from lab.models import labels
from lab.models.artifact import load_model, save_model, train_final
from lab.models.features import FEATURES
from lab.models.online import FeatureBuffer, ModelPredictor
from lab.models.train import _aligned, _fit_predict

FEATURE_COLUMNS = list(FEATURES)


# ---------- artifacts ----------

@pytest.fixture(scope="module")
def saved_models(tmp_path_factory, btc, features):
    out = {}
    for kind, y in {
        "vol": labels.forward_vol(btc, 10),
        "classification": labels.forward_regime(btc, 20),
        "regression": labels.forward_return(btc, 5),
    }.items():
        d = tmp_path_factory.mktemp(kind)
        model, Xa = train_final(kind, features, y)
        meta = save_model(model, d, kind=kind, target=str(y.name), horizon=5, features=FEATURE_COLUMNS,
                          train_start=Xa.index[0], train_end=Xa.index[-1], data_snapshot="test")
        out[kind] = (d, meta, model)
    return out


def test_meta_contents(saved_models):
    d, meta, _ = saved_models["vol"]
    on_disk = json.loads((d / "meta.json").read_text())
    assert on_disk == meta
    assert len(meta["model_sha256"]) == 64 and meta["features"] == FEATURE_COLUMNS


def test_tampered_model_is_rejected(saved_models, tmp_path):
    d, _, _ = saved_models["vol"]
    copy = tmp_path / "copy"
    copy.mkdir()
    for f in ("model.joblib", "meta.json"):
        (copy / f).write_bytes((d / f).read_bytes())
    with open(copy / "model.joblib", "ab") as fh:
        fh.write(b"tamper")
    with pytest.raises(ValueError):
        load_model(copy)


@pytest.mark.parametrize("kind", ["vol", "classification", "regression"])
def test_predictor_matches_model_and_ignores_column_order(saved_models, features, kind):
    d, _, model = saved_models[kind]
    pred = ModelPredictor(str(d))
    row = features.iloc[-1]
    shuffled = row[list(reversed(row.index))]
    assert pred.predict(row) == pytest.approx(pred.predict(shuffled))
    x = row.to_frame().T.astype(float)
    if kind == "classification":
        assert 0 <= pred.predict(row) <= 1
        assert pred.predict(row) == pytest.approx(model.predict_proba(x)[:, 1][0])
    else:  # "vol": AnchoredVolModel.predict already returns the anchored volatility
        assert pred.predict(row) == pytest.approx(model.predict(x)[0])


def test_saved_vol_model_is_the_model_that_was_validated(saved_models, btc, features):
    """Bug #17: train_final used to fit log(vol) from scratch and the predictor returned exp(pred), while CPCV
    and walk-forward validated the EWMA-anchored correction. The deployed forecast must equal the validated one."""
    d, _, _ = saved_models["vol"]
    Xa, ya = _aligned(features, labels.forward_vol(btc, 10))
    validated = _fit_predict("vol", Xa, ya, Xa.iloc[-5:], seed=0)
    pred = ModelPredictor(str(d))
    assert [pred.predict(Xa.iloc[i]) for i in range(-5, 0)] == pytest.approx(validated, rel=1e-12)
    ratio = [pred.predict(Xa.iloc[i]) / Xa["ewma_vol_20"].iloc[i] for i in range(-5, 0)]
    assert max(ratio) / min(ratio) < 3  # a correction on top of EWMA, not a forecast from scratch


def test_predictor_takes_the_live_buffer_dict_and_rejects_missing_features(saved_models, btc, features):
    d, _, _ = saved_models["regression"]
    pred = ModelPredictor(str(d))
    buf = FeatureBuffer()
    for ts, row in btc.iloc[-200:].iterrows():
        buf.update(ts, row.open, row.high, row.low, row.close, row.volume)
    live = buf.latest()
    assert isinstance(live, dict)
    assert pred.predict(live) == pred.predict(features.iloc[-1])  # bit-exact features, same forecast
    del live["vol_20"]
    with pytest.raises(ValueError, match="missing features"):
        pred.predict(live)
