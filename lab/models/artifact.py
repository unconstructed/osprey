"""Model files: save a trained model with its metadata, and refuse to load one that was changed.

A saved model is a directory holding two files:

- ``model.joblib``: the fitted model (joblib pickle).
- ``metadata.json``: format tag, model ``kind``, the ordered ``features`` it reads, label ``horizon``
  (bars), ``train_window`` (ISO-8601 UTC start and end), ``data_snapshot`` (catalog SNAPSHOT id),
  ``anchor`` (the EWMA feature a volatility model corrects; None otherwise), library versions, and the
  ``sha256`` of ``model.joblib``.

:func:`load_model` hashes ``model.joblib`` BEFORE unpickling it and refuses (ValueError "tampered") when
the hash differs from the metadata, so a modified or corrupted file is never executed. After loading
it checks the model against its metadata again (kind, feature list), exactly as :func:`save_model` does.

Kinds (``KINDS``):
- ``"vol"``: a :class:`lab.models.train.VolModel` (EWMA-anchored volatility forecast).
- ``"classification"``: a classifier with ``predict_proba`` (e.g. regime); predictions are P(class 1).
- ``"regression"``: any other regressor with ``predict`` (e.g. cross-sectional rank).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import joblib
import lightgbm
import numpy as np
import pandas as pd
import sklearn

from lab.models.train import VolModel

__all__ = ["FORMAT", "KINDS", "METADATA_FILE", "MODEL_FILE", "file_sha256", "load_model", "save_model"]

FORMAT = "osprey.model/1"
KINDS = ("vol", "classification", "regression")
MODEL_FILE = "model.joblib"
METADATA_FILE = "metadata.json"
_REQUIRED = ("format", "kind", "features", "horizon", "train_window", "data_snapshot", "anchor", "sha256")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def file_sha256(path: str | os.PathLike) -> str:
    """Hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_model(
    model,
    path: str | os.PathLike,
    *,
    features: Sequence[str],
    horizon: int,
    train_window,
    data_snapshot: str,
    kind: str,
) -> Path:
    """Write ``model`` and its metadata to the directory ``path`` (created if needed); return ``path``.

    ``features``: the model's input columns in order (must match the model's own record of them).
    ``horizon``: label horizon in bars (int >= 1). ``train_window``: ``(start, end)`` of the training data,
    anything ``pandas.Timestamp`` accepts (naive means UTC), ``start <= end``. ``data_snapshot``: the data
    snapshot id. ``kind``: one of ``KINDS``. Every invalid argument raises ValueError before anything is
    written. Existing files in ``path`` are replaced (each via a temporary file and an atomic rename).
    """
    features = _check_features(features)
    _check_model(model, kind, features)
    meta: dict[str, Any] = {
        "format": FORMAT,
        "kind": kind,
        "features": features,
        "horizon": _check_horizon(horizon),
        "train_window": _check_window(train_window),
        "data_snapshot": _check_snapshot(data_snapshot),
        "anchor": model.anchor if kind == "vol" else None,
        "versions": {
            "python": platform.python_version(),
            "lightgbm": lightgbm.__version__,
            "scikit-learn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "joblib": joblib.__version__,
        },
    }
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    model_file = out / MODEL_FILE
    tmp = out / (MODEL_FILE + ".tmp")
    joblib.dump(model, tmp)
    os.replace(tmp, model_file)
    meta["sha256"] = file_sha256(model_file)
    tmp = out / (METADATA_FILE + ".tmp")
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, out / METADATA_FILE)
    return out


def load_model(path: str | os.PathLike) -> tuple[Any, dict]:
    """Load ``(model, metadata)`` from a directory written by :func:`save_model`.

    Raises ValueError containing "tampered" when ``model.joblib`` doesn't match the recorded SHA-256 (the
    file is not unpickled), ValueError for unreadable or inconsistent metadata, FileNotFoundError when a
    file is missing.
    """
    root = Path(path)
    meta = _read_metadata(root / METADATA_FILE)
    model_file = root / MODEL_FILE
    digest = file_sha256(model_file)
    if digest != meta["sha256"]:
        raise ValueError(
            f"{model_file} was tampered with or corrupted: its SHA-256 is {digest}, "
            f"the metadata records {meta['sha256']}; refusing to load it"
        )
    model = joblib.load(model_file)
    _check_model(model, meta["kind"], _check_features(meta["features"]))
    if meta["kind"] == "vol" and meta["anchor"] != model.anchor:
        raise ValueError(f"metadata anchor {meta['anchor']!r} differs from the model's {model.anchor!r}")
    return model, meta


# ----------------------------------------------------------------------------- validation


def _check_features(features) -> list[str]:
    if isinstance(features, str) or not isinstance(features, Sequence | np.ndarray | pd.Index):
        raise ValueError("features must be a sequence of column names")
    out = list(features)
    if not out or not all(isinstance(f, str) and f for f in out):
        raise ValueError("features must be a non-empty list of non-empty strings")
    if len(set(out)) != len(out):
        raise ValueError("features contain duplicates")
    return out


def _check_model(model, kind: str, features: list[str]) -> None:
    """The model fits ``kind`` and reads exactly ``features`` (in order, when it records them)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    is_vol = isinstance(model, VolModel)
    if kind == "vol":
        if not is_vol:
            raise ValueError(f"kind 'vol' needs a VolModel, got {type(model).__name__}")
        if model.anchor is None or model.anchor not in model.features:
            raise ValueError("a vol model needs an anchor column among its features (fit it on a named column)")
        own = list(model.features)
    else:
        if is_vol:
            raise ValueError(f"a VolModel must be saved with kind 'vol', not {kind!r}")
        has_proba = hasattr(model, "predict_proba")
        if kind == "classification" and not has_proba:
            raise ValueError("kind 'classification' needs a model with predict_proba")
        if kind == "regression" and (has_proba or not hasattr(model, "predict")):
            raise ValueError("kind 'regression' needs a model with predict and without predict_proba")
        names = getattr(model, "feature_names_in_", None)
        own = None if names is None else [str(n) for n in names]
    if own is not None and own != features:
        raise ValueError(f"features {features} differ from the columns the model was fit on {own}")


def _check_horizon(horizon) -> int:
    if isinstance(horizon, bool) or not isinstance(horizon, int | np.integer) or horizon < 1:
        raise ValueError(f"horizon must be an int >= 1 (bars), got {horizon!r}")
    return int(horizon)


def _utc(ts) -> pd.Timestamp:
    stamp = pd.Timestamp(ts)
    if pd.isna(stamp):
        raise ValueError("train_window contains a missing timestamp")
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _check_window(window) -> list[str]:
    if isinstance(window, str) or not isinstance(window, Sequence) or len(window) != 2:
        raise ValueError("train_window must be a (start, end) pair")
    start, end = (_utc(t) for t in window)
    if start > end:
        raise ValueError(f"train_window start {start} is after its end {end}")
    return [start.isoformat(), end.isoformat()]


def _check_snapshot(snapshot) -> str:
    if not isinstance(snapshot, str) or not snapshot.strip():
        raise ValueError("data_snapshot must be a non-empty string (the data SNAPSHOT id)")
    return snapshot


def _read_metadata(path: Path) -> dict:
    try:
        meta = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError(f"{path} must hold a JSON object")
    missing = [k for k in _REQUIRED if k not in meta]
    if missing:
        raise ValueError(f"{path} is missing keys: {missing}")
    if meta["format"] != FORMAT:
        raise ValueError(f"{path} has format {meta['format']!r}, expected {FORMAT!r}")
    if not isinstance(meta["sha256"], str) or not _SHA256.fullmatch(meta["sha256"]):
        raise ValueError(f"{path} has no valid sha256 (64 lowercase hex digits)")
    return meta
