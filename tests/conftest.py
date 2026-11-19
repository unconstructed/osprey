"""Shared test setup: hypothesis profiles and market fixtures.

Profiles (select with HYPOTHESIS_PROFILE):
- ``fast`` (default): 40 examples per property, every normal run.
- ``deep``: 500 examples per property, before merging changes to lab/.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "fast",
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.register_profile(
    "deep",
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "fast"))


@pytest.fixture(scope="session")
def market() -> dict[str, pd.DataFrame]:
    """Synthetic 1500-day BTC + ETH daily bars (seed 21). Treat as read-only."""
    from lab.data.synthetic import synthetic_market

    return synthetic_market(1500, seed=21)


@pytest.fixture(scope="session")
def btc(market) -> pd.DataFrame:
    return market["BTC"]


@pytest.fixture(scope="session")
def features(btc) -> pd.DataFrame:
    from lab.models.features import compute_features

    return compute_features(btc)


def build_bars(close_path, start="2020-01-01", spread=0.01, volume=1000.0) -> pd.DataFrame:
    """Valid daily OHLCV bars from a list of closes.

    open = previous close (the first open equals the first close); high/low add ``spread`` around the body.
    """
    close = np.asarray(close_path, dtype=float)
    if close.ndim != 1 or len(close) < 2:
        raise ValueError("close_path needs at least 2 values")
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + spread / 2)
    low = np.minimum(open_, close) * (1 - spread / 2)
    index = pd.date_range(start, periods=len(close), freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": np.full(len(close), float(volume))},
        index=index,
    )


@pytest.fixture
def make_bars():
    """``make_bars(close_path, start=..., spread=..., volume=...)`` -> hand-built bars."""
    return build_bars
