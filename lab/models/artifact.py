"""Versioned model artifacts: the model file plus the metadata production needs.

In the full lab these are also logged to MLflow; this file format is what a Nautilus
strategy loads read-only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib

from .train import AnchoredVolModel, make_model


def train_final(kind: str, X, y, seed: int = 0):
    """Fit on all usable rows (only after validation has passed).

    A "vol" model is the same EWMA-anchored model that CPCV and walk-forward validated
    (``AnchoredVolModel``), not a from-scratch fit of log(volatility).
    """
    from .train import _aligned

    Xa, ya = _aligned(X, y)
    if kind == "vol":
        return AnchoredVolModel(seed).fit(Xa, ya), Xa
    model = make_model(kind, seed)
    model.fit(Xa, ya)
    return model, Xa


def save_model(model, out_dir: str | Path, *, kind: str, target: str, horizon: int,
               features: list[str], train_start, train_end, data_snapshot: str,
               notes: str = "") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "model.joblib")
    digest = hashlib.sha256((out / "model.joblib").read_bytes()).hexdigest()
    meta = {
        "kind": kind,
        "target": target,
        "horizon": horizon,
        "features": list(features),
        "train_start": str(train_start),
        "train_end": str(train_end),
        "data_snapshot": data_snapshot,
        "model_sha256": digest,
        "created_at": datetime.now(UTC).isoformat(),
        "notes": notes,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def load_model(out_dir: str | Path):
    out = Path(out_dir)
    meta = json.loads((out / "meta.json").read_text())
    digest = hashlib.sha256((out / "model.joblib").read_bytes()).hexdigest()
    if digest != meta["model_sha256"]:
        raise ValueError("model file does not match its recorded hash")
    return joblib.load(out / "model.joblib"), meta
