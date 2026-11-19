"""Synthetic test data (lab/data/synthetic.py; excluded from coverage as scaffolding, tested anyway).

- ``synthetic_market``, ``synthetic_bars`` and ``shuffled_market`` always produce valid bars.
- Everything is seed-deterministic.
- The generator has what the lab's statistics need: volatility clustering (|r| autocorrelation) and
  BTC/ETH correlation.
- ``shuffled_market`` (the luck control) keeps the multiset of bar shapes and the same-day BTC/ETH
  pairing, but destroys the volatility clustering.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.data.synthetic import shuffled_market, synthetic_bars, synthetic_market
from lab.runner.interface import validate_bars

ASSET_SETS = [("BTC",), ("BTC", "ETH"), ("BTC", "ETH", "SOL")]


def log_returns(bars: pd.DataFrame) -> np.ndarray:
    return np.diff(np.log(bars["close"].to_numpy()))


def lag1_autocorr(x: np.ndarray) -> float:
    x = x - x.mean()
    return float(np.sum(x[1:] * x[:-1]) / np.sum(x * x))


def bar_shapes(bars: pd.DataFrame) -> np.ndarray:
    """Per bar: gap from the previous close, open-to-close move, upper and lower wick, volume.

    Bar 0's "previous close" is its own open (as in shuffled_market). Rows are sorted by volume, which
    the shuffle copies bit for bit (the ratios are recomputed and may differ in the last bit), so two
    markets with the same bars in a different order give the same array.
    """
    o, h, lo, c, v = (bars[col].to_numpy() for col in ("open", "high", "low", "close", "volume"))
    prev_c = np.concatenate([[o[0]], c[:-1]])
    shapes = np.column_stack([o / prev_c, c / o, h / np.maximum(o, c), lo / np.minimum(o, c), v])
    return shapes[np.argsort(v, kind="stable")]


# ---------------------------------------------------------------- validity


@given(n_days=st.integers(2, 400), seed=st.integers(0, 2**32 - 1), assets=st.sampled_from(ASSET_SETS))
def test_synthetic_market_bars_are_valid(n_days, seed, assets):
    market = synthetic_market(n_days, assets=assets, seed=seed, start="2020-02-01")
    assert list(market) == list(assets)
    first = market[assets[0]].index
    assert first[0] == pd.Timestamp("2020-02-01", tz="UTC") and len(first) == n_days
    assert (np.diff(first.asi8) == np.diff(first.asi8)[0]).all()  # one bar per day
    for bars in market.values():
        validate_bars(bars)
        assert bars.index.equals(first)


@given(n_days=st.integers(2, 400), seed=st.integers(0, 2**32 - 1), shuffle_seed=st.integers(0, 2**32 - 1))
def test_shuffled_market_bars_are_valid(n_days, seed, shuffle_seed):
    market = synthetic_market(n_days, seed=seed)
    shuffled = shuffled_market(market, seed=shuffle_seed)
    for asset, bars in shuffled.items():
        validate_bars(bars)
        assert bars.index.equals(market[asset].index)


@given(n_days=st.integers(2, 300), seed=st.integers(0, 2**32 - 1))
def test_synthetic_bars_is_the_single_asset_market(n_days, seed):
    bars = synthetic_bars(n_days, seed=seed)
    validate_bars(bars)
    pd.testing.assert_frame_equal(bars, synthetic_market(n_days, assets=("BTC",), seed=seed)["BTC"])


def test_too_few_days_raise():
    with pytest.raises(ValueError, match="n_days must be at least 2"):
        synthetic_market(1)


# ---------------------------------------------------------------- determinism


def test_seed_determinism(market):
    again = synthetic_market(1500, seed=21)
    for asset in market:
        pd.testing.assert_frame_equal(again[asset], market[asset], check_exact=True)
    other = synthetic_market(1500, seed=22)
    assert not np.allclose(other["BTC"]["close"], market["BTC"]["close"])
    pd.testing.assert_frame_equal(synthetic_bars(300, seed=5), synthetic_bars(300, seed=5), check_exact=True)
    s1, s2, s3 = (shuffled_market(market, seed=s) for s in (1, 1, 2))
    pd.testing.assert_frame_equal(s1["ETH"], s2["ETH"], check_exact=True)
    assert not np.allclose(s1["ETH"]["close"], s3["ETH"]["close"])


# ---------------------------------------------------------------- statistical character


def test_generator_has_volatility_clustering_and_correlated_assets(market):
    btc, eth = log_returns(market["BTC"]), log_returns(market["ETH"])
    band = 4 / np.sqrt(len(btc))  # 4 standard errors of a lag-1 autocorrelation under independence
    assert lag1_autocorr(np.abs(btc)) > band
    assert lag1_autocorr(np.abs(eth)) > band
    assert np.corrcoef(btc, eth)[0, 1] > 0.5
    assert eth.std() > btc.std()  # ETH is the more volatile asset


@pytest.mark.parametrize("seed", range(5))
def test_shuffle_keeps_bar_shapes_and_pairing(market, seed):
    shuffled = shuffled_market(market, seed=seed)
    for asset in market:
        np.testing.assert_allclose(bar_shapes(shuffled[asset]), bar_shapes(market[asset]), rtol=1e-9)
        # close-to-close returns are a permutation of the original ones
        np.testing.assert_allclose(
            np.sort(log_returns(shuffled[asset])), np.sort(log_returns(market[asset])), rtol=1e-9, atol=1e-12
        )
    # assets are permuted jointly: same-day pairs, hence the BTC/ETH correlation, are unchanged
    before = np.corrcoef(log_returns(market["BTC"]), log_returns(market["ETH"]))[0, 1]
    after = np.corrcoef(log_returns(shuffled["BTC"]), log_returns(shuffled["ETH"]))[0, 1]
    assert after == pytest.approx(before, rel=1e-9)


@pytest.mark.parametrize("seed", range(5))
def test_shuffle_destroys_volatility_clustering(market, seed):
    shuffled = shuffled_market(market, seed=seed)
    for asset in market:
        r = log_returns(shuffled[asset])
        # a random order: |r| autocorrelation within 4 standard errors of 0 (the original is ~8 away)
        assert abs(lag1_autocorr(np.abs(r))) < 4 / np.sqrt(len(r)), asset


def test_shuffle_autocorrelation_is_zero_on_average(market):
    """Averaged over 20 shuffles the |r| autocorrelation is 0 within 3 standard errors of the mean."""
    acs = [lag1_autocorr(np.abs(log_returns(shuffled_market(market, seed=s)["BTC"]))) for s in range(20)]
    se = (1 / np.sqrt(len(market["BTC"]) - 1)) / np.sqrt(len(acs))
    assert abs(np.mean(acs)) < 3 * se
    assert lag1_autocorr(np.abs(log_returns(market["BTC"]))) > 20 * se
