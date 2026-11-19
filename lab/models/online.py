"""Live feature computation for use inside a Nautilus strategy.

``FeatureBuffer`` keeps the last bars and returns the same feature values as
:func:`lab.models.features.compute_features` would for that bar on the full history, bit for bit
(tested on every bar). It runs the very same :func:`lab.models.features.feature_matrix` on its buffer;
every feature reads a fixed trailing window, so the last ``WARMUP`` bars are all it needs.

::

    def on_start(self):
        self.features = FeatureBuffer()

    def on_bar(self, bar):
        self.features.update(bar.ts_event, bar.open, bar.high, bar.low, bar.close, bar.volume)
        feats = self.features.latest()
        if feats is None:
            return  # still warming up

``ModelPredictor`` (from the starter code) loads a saved model read-only (:func:`lab.models.artifact.load_model`,
which refuses a tampered file) and turns one ``{feature: value}`` mapping, such as ``FeatureBuffer.latest()``,
into one forecast::

        self.vol_model = ModelPredictor("models/vol_20d")
        forecast_vol = self.vol_model.predict(feats)
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from datetime import datetime

import numpy as np
import pandas as pd

from lab.models.artifact import load_model
from lab.models.features import FEATURES, WARMUP, feature_matrix


def _utc(ts: pd.Timestamp | datetime | np.datetime64 | int | str) -> pd.Timestamp:
    """A bar timestamp as a UTC ``Timestamp``. An int is nanoseconds since the epoch (Nautilus
    ``ts_event``); a naive timestamp is taken to be UTC."""
    stamp = pd.Timestamp(ts)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


class FeatureBuffer:
    """Rolling buffer of bars that yields the latest ``FEATURES`` values, point in time.

    ``maxlen`` is the number of bars kept (default and minimum: ``WARMUP``). Bars must arrive in
    strictly increasing time order and be valid (finite, positive prices, ``low <= open, close <= high``,
    ``volume >= 0``); anything else raises ``ValueError`` and leaves the buffer unchanged.
    Price arguments may be any object ``float()`` accepts (e.g. Nautilus ``Price`` and ``Quantity``).
    """

    def __init__(self, maxlen: int | None = None) -> None:
        maxlen = WARMUP if maxlen is None else maxlen
        if isinstance(maxlen, bool) or not isinstance(maxlen, int) or maxlen < WARMUP:
            raise ValueError(f"maxlen must be an int >= WARMUP ({WARMUP}), got {maxlen!r}")
        self.maxlen = maxlen
        self._bars: deque[tuple[float, float, float, float, float]] = deque(maxlen=maxlen)
        self._last_ts: pd.Timestamp | None = None
        self._latest: dict[str, float] | None = None

    def __len__(self) -> int:
        return len(self._bars)

    @property
    def ready(self) -> bool:
        """True once ``WARMUP`` bars have been seen, i.e. ``latest()`` returns values."""
        return len(self._bars) >= WARMUP

    @property
    def last_ts(self) -> pd.Timestamp | None:
        """Close time of the newest bar, or None before the first update."""
        return self._last_ts

    def update(self, ts, open, high, low, close, volume) -> None:
        """Add the bar that closed at ``ts``."""
        stamp = _utc(ts)
        if pd.isna(stamp):
            raise ValueError("bar timestamp is missing (NaT)")
        if self._last_ts is not None and stamp <= self._last_ts:
            raise ValueError(
                f"bars must arrive in strictly increasing time order: {stamp} after {self._last_ts}"
            )
        o, h, lo, c, v = (float(x) for x in (open, high, low, close, volume))
        if not all(math.isfinite(x) for x in (o, h, lo, c, v)):
            raise ValueError("bar contains NaN or infinite values")
        if min(o, h, lo, c) <= 0:
            raise ValueError("bar contains non-positive prices")
        if v < 0:
            raise ValueError("bar has negative volume")
        if h < max(o, c) or lo > min(o, c):
            raise ValueError("bar violates low <= open, close <= high")
        self._bars.append((o, h, lo, c, v))
        self._last_ts = stamp
        self._latest = None

    def latest(self) -> dict[str, float] | None:
        """Features of the newest bar as ``{name: value}`` in ``FEATURES`` order, or None while warming up."""
        if not self.ready:
            return None
        if self._latest is None:
            window = np.array(list(self._bars)[-WARMUP:], dtype=float)
            arrays = (np.ascontiguousarray(window[:, j]) for j in range(5))
            row = feature_matrix(*arrays)[-1]
            self._latest = dict(zip(FEATURES, row.tolist(), strict=True))
        return dict(self._latest)


class ModelPredictor:
    """Read-only wrapper around a saved model artifact (the starter's, taking a mapping).

    ``predict`` reads the features by NAME in the order the metadata records, so the mapping's key order never
    matters and extra keys are ignored: pass ``FeatureBuffer.latest()`` (a dict) or a ``pd.Series`` row of
    ``compute_features``. A missing feature raises ValueError instead of becoming NaN (LightGBM would accept a NaN
    silently). Kind "vol" returns the EWMA-anchored volatility forecast exactly as it was validated
    (:class:`lab.models.train.AnchoredVolModel`); "classification" the probability of class 1; "regression" the
    regressor's prediction.
    """

    def __init__(self, artifact_dir: str):
        self.model, self.meta = load_model(artifact_dir)
        self.columns = list(self.meta.get("features", FEATURES))
        self.kind = self.meta["kind"]

    def predict(self, features: Mapping[str, float]) -> float:
        missing = [c for c in self.columns if c not in features]
        if missing:
            raise ValueError(f"missing features for the model: {missing}")
        x = pd.DataFrame([[float(features[c]) for c in self.columns]], columns=self.columns)
        if self.kind == "classification":
            return float(self.model.predict_proba(x)[:, 1][0])
        return float(self.model.predict(x)[0])
