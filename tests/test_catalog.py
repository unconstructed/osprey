"""lab/data/catalog.py: instruments and bars into a Nautilus v2 ParquetDataCatalog and back (load_bars)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from nautilus_trader.model import Bar, BarType, Price, Quantity
from nautilus_trader.persistence import ParquetDataCatalog

from lab.data import catalog as cat
from lab.runner.interface import validate_bars

SID = "0123456789abcdef"


def make_bars(close, start="2021-01-02", freq="D", decimals=2, volume=None) -> pd.DataFrame:
    close = np.round(np.asarray(close, dtype=float), decimals)
    open_ = np.concatenate([[close[0]], close[:-1]])
    idx = pd.DatetimeIndex(pd.date_range(start, periods=len(close), freq=freq, tz="UTC", name="ts"), freq=None).as_unit("us")
    vol = np.asarray(volume, dtype=float) if volume is not None else np.full(len(close), 1.5)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.round(np.maximum(open_, close) * 1.01, decimals),
            "low": np.round(np.minimum(open_, close) * 0.99, decimals),
            "close": close,
            "volume": vol,
        },
        index=idx,
    )


def write(tmp_path, frames: dict[tuple[str, str], pd.DataFrame], instrument=("BTC/USD.KRAKEN", "XBTUSD", "BTC", "USD")):
    p = cat.price_precision(*frames.values())
    series = {cat.bar_type(instrument[0], iv): cat.to_nautilus(f, cat.bar_type(instrument[0], iv), p) for (_, iv), f in frames.items()}
    cat.write_catalog(tmp_path, [cat.make_instrument(*instrument, p)], series)
    (tmp_path / cat.SNAPSHOT_FILE).write_text(json.dumps({"snapshot_id": SID}))
    return p


def test_bar_types():
    assert cat.bar_type("BTC/USD.KRAKEN", "1d") == "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL"
    assert cat.bar_type("ETHUSDT.BINANCE", "1h") == "ETHUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"
    with pytest.raises(ValueError, match="interval"):
        cat.bar_type("BTC/USD.KRAKEN", "15m")
    assert {v[0] for v in cat.INSTRUMENTS.values()} == {
        "BTC/USD.KRAKEN", "ETH/USD.KRAKEN", "BTCUSDT.BINANCE", "ETHUSDT.BINANCE", "BTC-USD.COINBASE", "ETH-USD.COINBASE",
    }


@pytest.mark.parametrize(
    "values, expected",
    [([122.0, 3.0], 0), ([123.61, 83462.7], 2), ([3.00001, 1.19999], 5), ([1e-05], 5), ([0.1 + 0.2], 17)],
)
def test_decimals_of_the_shortest_exact_form(values, expected):
    assert cat.decimals(np.array(values)) == expected


def test_decimals_rejects_non_finite():
    with pytest.raises(ValueError, match="precision"):
        cat.decimals(np.array([1.0, np.inf]))


def test_price_precision_over_every_frame_and_float_noise():
    assert cat.price_precision(make_bars([1.5, 2.25], decimals=2), make_bars([3.125, 4.0], decimals=3)) == 3
    noisy = make_bars([1.0, 2.0])
    noisy.iloc[0, 0] = 0.1 + 0.2
    with pytest.raises(ValueError, match="float noise"):
        cat.price_precision(noisy)


def test_instrument_fields():
    inst = cat.make_instrument("ETHUSDT.BINANCE", "ETHUSDT", "ETH", "USDT", 2)
    assert str(inst.id) == "ETHUSDT.BINANCE" and str(inst.raw_symbol) == "ETHUSDT"
    assert str(inst.base_currency) == "ETH" and str(inst.quote_currency) == "USDT"
    assert inst.price_precision == 2 and inst.size_precision == 8
    assert str(inst.price_increment) == "0.01" and str(inst.size_increment) == "0.00000001"
    assert str(cat.make_instrument("BTC/USD.KRAKEN", "XBTUSD", "BTC", "USD", 0).price_increment) == "1"


def test_nautilus_bars_are_stamped_at_the_close():
    b = make_bars([100.0, 101.5, 99.25])
    bars = cat.to_nautilus(b, "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL", 2)
    assert [x.ts_event for x in bars] == [x.ts_init for x in bars] == list(b.index.as_unit("ns").asi8)
    assert str(bars[0].bar_type) == "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL"
    assert bars[1].close == Price.from_str("101.50") and bars[1].volume == Quantity.from_str("1.50000000")


def test_round_trip_daily_and_hourly(tmp_path):
    rng = np.random.default_rng(7)
    daily = make_bars(30000 + rng.normal(0, 500, 40).cumsum(), decimals=1, volume=rng.uniform(0, 100, 40))
    hourly = make_bars(30000 + rng.normal(0, 50, 300).cumsum(), freq="h", decimals=1, volume=rng.uniform(0, 5, 300))
    p = write(tmp_path, {("kraken", "1d"): daily, ("kraken", "1h"): hourly})
    assert p == 1
    for iv, src in (("1d", daily), ("1h", hourly)):
        got = cat.load_bars("BTC/USD.KRAKEN", iv, catalog_dir=tmp_path)
        validate_bars(got)
        assert got.attrs == {"snapshot_id": SID, "bar_type": cat.bar_type("BTC/USD.KRAKEN", iv), "instrument": "BTC/USD.KRAKEN"}
        assert got.index.equals(src.index) and got.index.name == "ts" and str(got.index.tz) == "UTC"
        assert got.index.unit == "us" and list(got.columns) == ["open", "high", "low", "close", "volume"]
        pd.testing.assert_frame_equal(got, cat.stored_values(src, p), check_exact=True)
        prices = ["open", "high", "low", "close"]
        ulps = np.abs(got[prices].to_numpy() - src[prices].to_numpy()) / np.spacing(src[prices].to_numpy())
        assert ulps.max() <= 1  # float(Price) may differ from the source float in the last place only
        assert np.abs(got["volume"] - src["volume"]).max() <= 5e-9  # 8-decimal sizes


def test_load_bars_matches_the_live_conversion_bit_for_bit(tmp_path):
    """The live path converts each Nautilus Bar with float(); load_bars must give the same floats."""
    rng = np.random.default_rng(11)
    b = make_bars(rng.uniform(100, 100000, 400), decimals=2, volume=rng.uniform(0, 10, 400))
    write(tmp_path, {("kraken", "1d"): b})
    got = cat.load_bars("BTC/USD.KRAKEN", "1d", catalog_dir=tmp_path)
    live = ParquetDataCatalog(str(tmp_path)).query_bars(["BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL"])
    for col in ["open", "high", "low", "close", "volume"]:
        assert got[col].tolist() == [float(getattr(x, col)) for x in live]
    # the Price itself is exact: what was stored is the source decimal
    assert all(x.close == Price.from_str(repr(c)) for x, c in zip(live, b["close"].tolist(), strict=True))


@given(
    decimals=st.integers(0, 6),
    seed=st.integers(0, 2**32 - 1),
    n=st.integers(2, 60),
    scale=st.sampled_from([0.01, 1.0, 100.0, 50000.0]),
)
def test_round_trip_property(tmp_path_factory, decimals, seed, n, scale):
    rng = np.random.default_rng(seed)
    close = np.maximum(np.round(scale * np.exp(rng.normal(0, 0.05, n).cumsum()), decimals), 10.0**-decimals)
    b = make_bars(close, decimals=decimals, volume=np.round(rng.uniform(0, 1000, n), 8))
    d = tmp_path_factory.mktemp("rt")
    p = write(d, {("kraken", "1d"): b})
    assert p <= decimals
    got = cat.load_bars("BTC/USD.KRAKEN", "1d", catalog_dir=d)
    pd.testing.assert_frame_equal(got, cat.stored_values(b, p), check_exact=True)
    prices = ["open", "high", "low", "close"]
    assert (np.abs(got[prices].to_numpy() - b[prices].to_numpy()) <= np.spacing(b[prices].to_numpy())).all()
    # volumes with 8 decimals are stored exactly; float(Quantity) is within one unit in the last place
    assert (np.abs(got["volume"].to_numpy() - b["volume"].to_numpy()) <= np.spacing(b["volume"].to_numpy())).all()


def test_start_and_end_are_inclusive_close_times(tmp_path):
    b = make_bars(np.arange(100.0, 110.0))
    write(tmp_path, {("kraken", "1d"): b})
    got = cat.load_bars("BTC/USD.KRAKEN", "1d", start="2021-01-04", end=pd.Timestamp("2021-01-06", tz="UTC"), catalog_dir=tmp_path)
    assert list(got.index) == list(b.index[2:5])
    later = cat.load_bars("BTC/USD.KRAKEN", "1d", start=pd.Timestamp("2021-01-09 01:00", tz="Europe/Paris"), catalog_dir=str(tmp_path))
    assert list(later.index) == list(b.index[7:])  # 01:00 Paris = 00:00 UTC, inclusive
    early = cat.load_bars("BTC/USD.KRAKEN", "1d", end="2021-01-03", catalog_dir=tmp_path)
    assert len(early) == 2


def test_load_bars_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="SNAPSHOT.json"):
        cat.load_bars("BTC/USD.KRAKEN", catalog_dir=tmp_path)
    write(tmp_path, {("kraken", "1d"): make_bars([1.0, 2.0, 3.0])})
    with pytest.raises(ValueError, match="no ETH/USD.KRAKEN-1-DAY"):
        cat.load_bars("ETH/USD.KRAKEN", catalog_dir=tmp_path)
    with pytest.raises(ValueError, match="no BTC/USD.KRAKEN-1-HOUR"):
        cat.load_bars("BTC/USD.KRAKEN", "1h", catalog_dir=tmp_path)
    with pytest.raises(ValueError, match="no BTC/USD.KRAKEN-1-DAY"):
        cat.load_bars("BTC/USD.KRAKEN", start="2030-01-01", catalog_dir=tmp_path)
    with pytest.raises(ValueError, match="after end"):
        cat.load_bars("BTC/USD.KRAKEN", start="2021-01-05", end="2021-01-04", catalog_dir=tmp_path)


def test_ts_event_must_equal_ts_init(tmp_path):
    bt = BarType.from_str("BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL")
    day = 86_400 * 10**9
    p = Price.from_str("1.0")
    bars = [Bar(bt, p, p, p, p, Quantity.from_str("1"), day * (i + 1) - day, day * (i + 1)) for i in range(3)]
    cat.write_catalog(tmp_path, [], {str(bt): bars})
    (tmp_path / cat.SNAPSHOT_FILE).write_text(json.dumps({"snapshot_id": SID}))
    with pytest.raises(ValueError, match="ts_event differs from ts_init"):
        cat.load_bars("BTC/USD.KRAKEN", catalog_dir=tmp_path)


def test_overlapping_files_in_the_catalog_are_refused(tmp_path):
    b = make_bars([1.0, 2.0, 3.0, 4.0])
    write(tmp_path, {("kraken", "1d"): b})
    again = cat.to_nautilus(b.iloc[1:], "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL", 2)
    ParquetDataCatalog(str(tmp_path)).write_bars(again, skip_disjoint_check=True)
    with pytest.raises(ValueError, match="not strictly increasing"):
        cat.load_bars("BTC/USD.KRAKEN", catalog_dir=tmp_path)


def test_instruments_are_in_the_catalog(tmp_path):
    write(tmp_path, {("binance", "1d"): make_bars([100.12, 101.5])}, ("BTCUSDT.BINANCE", "BTCUSDT", "BTC", "USDT"))
    (inst,) = ParquetDataCatalog(str(tmp_path)).instruments()
    assert str(inst.id) == "BTCUSDT.BINANCE" and inst.price_precision == 2 and inst.size_precision == 8


@pytest.mark.parametrize("bad", [None, "0123", "0123456789ABCDEF", 12])
def test_snapshot_id_must_be_16_lowercase_hex(tmp_path, bad):
    (tmp_path / cat.SNAPSHOT_FILE).write_text(json.dumps({"snapshot_id": bad}))
    with pytest.raises(ValueError, match="16 lowercase hex"):
        cat.snapshot_id(tmp_path)


def test_snapshot_id_reads_the_file(tmp_path):
    (tmp_path / cat.SNAPSHOT_FILE).write_text(json.dumps({"snapshot_id": SID, "created": "x"}))
    assert cat.snapshot_id(tmp_path) == SID
    with pytest.raises(FileNotFoundError, match="lab.data.build"):
        cat.snapshot_id(tmp_path / "nope")
