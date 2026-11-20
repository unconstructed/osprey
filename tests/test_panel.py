"""lab/data/panel.py: the BTC + ETH panel (pinned format, test-window guard, alignment, point in time).

No network and no real catalog: tiny Nautilus catalogs are written in tmp_path (as tests/test_catalog.py does),
or a ``loader`` serving in-memory bars is injected.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.data import catalog as cat
from lab.data import panel as pn
from lab.data.external import HoldoutWindowError
from lab.runner.interface import validate_bars

SID = "0123456789abcdef"
CUT = pd.Timestamp("2024-07-01", tz="UTC")  # close of the last validate bar (config/splits.yaml)
TRAIN_START = pd.Timestamp("2017-01-01", tz="UTC")
DAY = pd.Timedelta(days=1)
FIELDS = ["open", "high", "low", "close", "volume"]


def make_bars(index, base: float, decimals: int = 2) -> pd.DataFrame:
    """Valid bars on ``index`` (close times) with prices around ``base`` that differ on every bar."""
    index = pd.DatetimeIndex(index, name="ts").as_unit("us")
    n = len(index)
    close = np.round(base * (1 + 0.01 * np.sin(np.arange(n) + base)) + 0.01 * np.arange(n), decimals)
    open_ = np.round(close * 0.995, decimals)
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": np.round(np.maximum(open_, close) * 1.01, decimals),
            "low": np.round(np.minimum(open_, close) * 0.99, decimals),
            "close": close,
            "volume": np.round(1.0 + np.arange(n) * 0.125 + base / 1000, 8),
        },
        index=index,
    )
    return frame


def utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def grid(first, last, freq="D") -> pd.DatetimeIndex:
    return pd.date_range(utc(first), utc(last), freq=freq, name="ts")


def without(index: pd.DatetimeIndex, *drop) -> pd.DatetimeIndex:
    return index[~index.isin(pd.DatetimeIndex([utc(d) for d in drop]))]


class FakeLoader:
    """Serves in-memory bars like ``catalog.load_bars`` (inclusive close-time bounds) and records each call."""

    def __init__(self, frames: dict[str, pd.DataFrame], sid: str = SID):
        self.frames, self.sid, self.calls = frames, sid, []

    def __call__(self, instrument, interval, start, end, catalog_dir):
        self.calls.append((instrument, interval, start, end))
        f = self.frames[instrument]
        out = f.loc[(f.index >= start) & (f.index <= end)].copy()
        out.attrs = {
            "snapshot_id": self.sid,
            "bar_type": cat.bar_type(instrument, interval),
            "instrument": instrument,
        }
        return out


def kraken(btc: pd.DataFrame, eth: pd.DataFrame, **kw) -> FakeLoader:
    return FakeLoader({"BTC/USD.KRAKEN": btc, "ETH/USD.KRAKEN": eth}, **kw)


def write_catalog(path, source: str, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
    """A tiny Nautilus catalog with both instruments of ``source`` and a SNAPSHOT.json; ``frames`` maps
    ``(asset, interval)`` to bars."""
    instruments, series = [], {}
    for asset in pn.ASSETS:
        inst = cat.INSTRUMENTS[(source, asset)]
        mine = {iv: f for (a, iv), f in frames.items() if a == asset}
        p = cat.price_precision(*mine.values())
        instruments.append(cat.make_instrument(*inst, p))
        for iv, f in mine.items():
            bt = cat.bar_type(inst[0], iv)
            series[bt] = cat.to_nautilus(f, bt, p)
    cat.write_catalog(path, instruments, series)
    (path / cat.SNAPSHOT_FILE).write_text(json.dumps({"snapshot_id": SID}))


# ------------------------------------------------------------------------------------------ sources


def test_instruments_per_source():
    """The instrument ids of the snapshot's series (data/catalog/SNAPSHOT.json)."""
    assert pn.instruments("KRAKEN") == {"BTC": "BTC/USD.KRAKEN", "ETH": "ETH/USD.KRAKEN"}
    assert pn.instruments("BINANCE") == {"BTC": "BTCUSDT.BINANCE", "ETH": "ETHUSDT.BINANCE"}
    assert list(pn.instruments("KRAKEN")) == ["BTC", "ETH"]


@pytest.mark.parametrize("bad", ["COINBASE", "kraken", "Binance", "", None, 1])
def test_bad_source_raises_before_loading(bad):
    def loader(*args, **kwargs):
        raise AssertionError("must not be called")

    with pytest.raises(ValueError, match="source must be one of"):
        pn.load_panel(bad, last_close=CUT, loader=loader)
    with pytest.raises(ValueError, match="source must be one of"):
        pn.instruments(bad)


@pytest.mark.parametrize("bad", ["15m", "1D", "", None])
def test_bad_interval_raises(bad):
    with pytest.raises(ValueError, match="interval must be one of"):
        pn.load_panel("KRAKEN", bad, last_close=CUT, loader=kraken(None, None))


# ------------------------------------------------------------------------------------------ format


def assert_pinned_format(panel: pd.DataFrame, source: str, interval: str) -> None:
    assert isinstance(panel.columns, pd.MultiIndex)
    assert list(panel.columns.names) == ["asset", "field"]
    assert list(panel.columns) == [(a, f) for a in ("BTC", "ETH") for f in FIELDS]
    assert list(panel.columns.get_level_values("asset").unique()) == ["BTC", "ETH"]
    assert (panel.dtypes == np.float64).all() and len(panel.dtypes) == 10
    idx = panel.index
    assert (
        isinstance(idx, pd.DatetimeIndex) and idx.name == "ts" and str(idx.tz) == "UTC" and idx.unit == "us"
    )
    assert idx.is_monotonic_increasing and not idx.has_duplicates
    assert tuple(panel.attrs) == pn.ATTR_KEYS == ("snapshot_id", "instruments", "bar_type", "alignment")
    assert panel.attrs["snapshot_id"] == SID
    assert panel.attrs["instruments"] == pn.instruments(source)
    assert panel.attrs["bar_type"] == {
        a: cat.bar_type(pn.instruments(source)[a], interval) for a in ("BTC", "ETH")
    }
    al = panel.attrs["alignment"]
    assert set(al) == {"rule", "request", "rows", "common", "first", "last", "dropped", "missing"}
    assert (
        al["common"] == len(panel) and al["first"] == idx[0].isoformat() and al["last"] == idx[-1].isoformat()
    )
    for asset in ("BTC", "ETH"):
        block = panel[asset]
        assert list(block.columns) == FIELDS
        validate_bars(block)


@pytest.mark.parametrize("source, interval, freq", [("kraken", "1d", "D"), ("binance", "1h", "h")])
def test_format_from_a_nautilus_catalog(tmp_path, source, interval, freq):
    """Default loader (lab.data.catalog.load_bars): the pinned format, values as the catalog stores them."""
    idx = grid("2024-06-20", "2024-07-03", freq)  # reaches into the test window on purpose
    btc, eth = make_bars(without(idx, idx[3]), 60000.0, 2), make_bars(without(idx, idx[5], idx[6]), 3000.0, 3)
    write_catalog(tmp_path, source, {("BTC", interval): btc, ("ETH", interval): eth})
    panel = pn.load_panel(source.upper(), interval, last_close="2024-07-01", catalog_dir=tmp_path)
    assert_pinned_format(panel, source.upper(), interval)
    expected = idx[(idx <= CUT) & ~idx.isin([idx[3], idx[5], idx[6]])]
    assert panel.index.equals(pd.DatetimeIndex(expected).as_unit("us"))
    assert panel.index[-1] == CUT
    for asset, src in (("BTC", btc), ("ETH", eth)):
        stored = cat.stored_values(src.loc[panel.index], cat.price_precision(src))
        stored.columns.name = "field"
        pd.testing.assert_frame_equal(panel[asset], stored, check_exact=True, check_freq=False)
    al = panel.attrs["alignment"]
    assert al["dropped"]["BTC"]["closes"] == [idx[5].isoformat(), idx[6].isoformat()]
    assert al["dropped"]["ETH"]["closes"] == [idx[3].isoformat()]
    assert al["missing"]["closes"] == [idx[3].isoformat(), idx[5].isoformat(), idx[6].isoformat()]


def test_the_default_loader_is_the_catalog(monkeypatch):
    seen = []

    def fake(instrument, interval, start, end, catalog_dir):
        seen.append((instrument, interval, start, end, catalog_dir))
        out = make_bars(grid("2023-01-02", "2023-01-05"), 100.0)
        out.attrs = {"snapshot_id": SID}
        return out

    monkeypatch.setattr(cat, "load_bars", fake)
    panel = pn.load_panel("BINANCE", "1d", last_close="2023-01-05", catalog_dir="somewhere")
    assert [s[0] for s in seen] == ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    assert seen[0][1:] == ("1d", TRAIN_START, pd.Timestamp("2023-01-05", tz="UTC"), "somewhere")
    assert len(panel) == 4


def test_slicing_keeps_the_format_and_attrs():
    """lab/search slices bars with ``bars.iloc[...]``."""
    idx = grid("2023-01-02", "2023-01-20")
    panel = pn.load_panel(last_close="2023-01-20", loader=kraken(make_bars(idx, 50.0), make_bars(idx, 5.0)))
    part = panel.iloc[3:9]
    assert part.attrs == panel.attrs and list(part.columns) == list(panel.columns)
    validate_bars(part["ETH"])


def test_a_nanosecond_index_from_a_loader_comes_back_in_microseconds():
    idx = grid("2023-01-02", "2023-01-06").as_unit("ns")
    btc, eth = make_bars(idx, 50.0), make_bars(idx, 5.0)
    btc.index, eth.index = idx, idx
    assert btc.index.unit == "ns"
    panel = pn.load_panel(last_close="2023-01-06", loader=kraken(btc, eth))
    assert panel.index.unit == "us" and panel.index.equals(idx.as_unit("us"))


# ------------------------------------------------------------------------------------------ test-window guard


@pytest.mark.parametrize(
    "last",
    [
        CUT + pd.Timedelta(microseconds=1),
        "2024-07-01 00:00:01",
        pd.Timestamp("2024-07-02", tz="UTC"),
        "2024-07-01 01:30+01:00",  # 00:30 UTC
        "2024-07-01 00:00:00.000000001",
        "2026-11-20",
    ],
)
def test_a_request_after_the_cut_is_refused_before_loading(last):
    def loader(*args, **kwargs):
        raise AssertionError("must not be called")

    with pytest.raises(HoldoutWindowError, match="test window"):
        pn.load_panel("KRAKEN", "1d", last_close=last, loader=loader)
    with pytest.raises(HoldoutWindowError, match="test window"):
        pn.load_panel("BINANCE", "1h", last_close=last, loader=loader)


@pytest.mark.parametrize(
    "last", [CUT, "2024-07-01", "2024-07-01 01:00+01:00", pd.Timestamp("2024-06-30 20:00-04:00")]
)
def test_exactly_the_last_validate_close_is_allowed(last):
    idx = grid("2024-06-20", "2024-07-10")  # the source holds test-window bars
    loader = kraken(make_bars(idx, 50.0), make_bars(idx, 5.0))
    panel = pn.load_panel(last_close=last, loader=loader)
    assert panel.index[-1] == CUT
    assert [c[3] for c in loader.calls] == [CUT, CUT]  # never asked past the cut


@pytest.mark.parametrize("asset", ["BTC/USD.KRAKEN", "ETH/USD.KRAKEN"])
@pytest.mark.parametrize("late", [pd.Timedelta(microseconds=1), DAY, pd.Timedelta(days=400)])
def test_returned_data_after_the_cut_are_refused(asset, late):
    """A loader that ignores ``end`` and hands back a test-window bar: HoldoutWindowError, whatever was asked."""
    idx = grid("2024-06-20", "2024-06-30")

    def loader(instrument, interval, start, end, catalog_dir):
        mine = idx[idx <= end]  # honours end, except for the one late bar
        bars_idx = mine.append(pd.DatetimeIndex([CUT + late], name="ts")) if instrument == asset else mine
        out = make_bars(bars_idx, 50.0)
        out.attrs = {"snapshot_id": SID}
        return out

    for last in ("2024-06-25", CUT):
        with pytest.raises(HoldoutWindowError, match="after 2024-07-01"):
            pn.load_panel(last_close=last, loader=loader)


def test_the_holdout_check_comes_before_any_other_check():
    """A test-window bar is reported as such even when the bars are also broken in other ways."""

    def loader(instrument, interval, start, end, catalog_dir):
        # unsorted, one bar off the grid, a NaN price and no snapshot id
        out = make_bars(pd.DatetimeIndex([CUT + pd.Timedelta(hours=7), CUT - DAY]), 50.0)
        out.iloc[0, 0] = np.nan
        return out

    with pytest.raises(HoldoutWindowError):
        pn.load_panel(last_close="2024-06-01", loader=loader)


def test_the_cut_follows_config_dir(tmp_path):
    (tmp_path / "splits.yaml").write_text(
        "train: { start: 2017-01-01, end: 2019-12-31 }\nvalidate: { start: 2020-01-01, end: 2020-06-30 }\n"
        "test: { start: 2020-07-01, end: latest }\n"
    )
    idx = grid("2020-06-25", "2020-07-05")
    loader = kraken(make_bars(idx, 50.0), make_bars(idx, 5.0))
    with pytest.raises(HoldoutWindowError, match="2020-07-01"):
        pn.load_panel(last_close="2020-07-02", config_dir=tmp_path, loader=loader)
    panel = pn.load_panel(last_close="2020-07-01", config_dir=tmp_path, loader=loader)
    assert panel.index[-1] == pd.Timestamp("2020-07-01", tz="UTC")


# ------------------------------------------------------------------------------------------ windows and range


def test_only_train_and_validate_closes_are_kept():
    """The bar closing at 2017-01-01 00:00 is the 2016-12-31 bar: not in train (close-time rule)."""
    idx = grid("2016-12-25", "2017-01-06")
    loader = kraken(make_bars(idx, 50.0), make_bars(idx, 5.0))
    panel = pn.load_panel(last_close="2017-01-06", loader=loader)
    assert panel.index[0] == pd.Timestamp("2017-01-02", tz="UTC") and len(panel) == 5
    assert [c[2] for c in loader.calls] == [TRAIN_START, TRAIN_START]
    assert panel.attrs["alignment"]["rows"] == {"BTC": 5, "ETH": 5}


def test_the_windows_follow_config_dir(tmp_path):
    """The train and validate windows (not only the cut) come from ``config_dir``: train from 2018-01-01 here, so
    the loader is asked from there and the first close kept is 2018-01-02."""
    (tmp_path / "splits.yaml").write_text(
        "train: { start: 2018-01-01, end: 2019-12-31 }\nvalidate: { start: 2020-01-01, end: 2020-06-30 }\n"
        "test: { start: 2020-07-01, end: latest }\n"
    )
    idx = grid("2017-12-25", "2018-01-05")
    loader = kraken(make_bars(idx, 50.0), make_bars(idx, 5.0))
    panel = pn.load_panel(last_close="2018-01-05", config_dir=tmp_path, loader=loader)
    assert panel.index[0] == pd.Timestamp("2018-01-02", tz="UTC") and len(panel) == 4
    assert [c[2] for c in loader.calls] == [pd.Timestamp("2018-01-01", tz="UTC")] * 2


def test_a_bar_outside_the_windows_is_not_listed_as_dropped():
    """BTC's 2017-01-01 00:00 close (the 2016-12-31 bar) is removed by the window rule, not by the join, so ETH
    lacking it drops nothing, and ``rows`` and ``missing`` count only window bars."""
    idx = grid("2016-12-30", "2017-01-06")
    loader = kraken(make_bars(idx, 50.0), make_bars(without(idx, "2017-01-01"), 5.0))
    al = pn.load_panel(last_close="2017-01-06", loader=loader).attrs["alignment"]
    assert al["dropped"] == {"BTC": {"count": 0, "closes": []}, "ETH": {"count": 0, "closes": []}}
    assert al["rows"] == {"BTC": 5, "ETH": 5} and al["missing"] == {"count": 0, "closes": []}


def test_hourly_bars_start_at_the_first_train_hour():
    idx = grid("2016-12-31 20:00", "2017-01-01 05:00", "h")
    panel = pn.load_panel(
        "KRAKEN",
        "1h",
        last_close="2017-01-01 05:00",
        loader=kraken(make_bars(idx, 50.0), make_bars(idx, 5.0)),
    )
    assert panel.index[0] == pd.Timestamp("2017-01-01 01:00", tz="UTC") and len(panel) == 5
    assert panel.attrs["bar_type"]["ETH"] == "ETH/USD.KRAKEN-1-HOUR-LAST-EXTERNAL"


def test_start_is_inclusive_and_never_before_train():
    idx = grid("2016-12-25", "2017-01-20")
    loader = kraken(make_bars(idx, 50.0), make_bars(idx, 5.0))
    early = pn.load_panel(start="2015-01-01", last_close="2017-01-10", loader=loader)
    assert early.index[0] == pd.Timestamp("2017-01-02", tz="UTC")
    assert loader.calls[-1][2] == TRAIN_START
    assert early.attrs["alignment"]["request"] == {
        "start": "2015-01-01T00:00:00+00:00",
        "last_close": "2017-01-10T00:00:00+00:00",
    }
    later = pn.load_panel(
        start=pd.Timestamp("2017-01-05 01:00", tz="Europe/Paris"), last_close="2017-01-10", loader=loader
    )
    assert later.index[0] == pd.Timestamp("2017-01-05", tz="UTC") and later.index[-1] == pd.Timestamp(
        "2017-01-10", tz="UTC"
    )
    assert loader.calls[-1][2] == pd.Timestamp("2017-01-05", tz="UTC")
    none = pn.load_panel(last_close="2017-01-10", loader=loader)
    assert none.attrs["alignment"]["request"]["start"] is None
    with pytest.raises(ValueError, match="after last_close"):
        pn.load_panel(start="2017-01-11", last_close="2017-01-10", loader=loader)


@pytest.mark.parametrize("bad", [None, pd.NaT, "NaT", np.datetime64("NaT", "ns")])
def test_last_close_must_be_a_timestamp(bad):
    loader = kraken(None, None)
    with pytest.raises(ValueError, match="last_close must be a timestamp"):
        pn.load_panel(last_close=bad, loader=loader)
    with pytest.raises(ValueError, match="start must be a timestamp"):
        pn.load_panel(start=pd.NaT if bad is None else bad, last_close=CUT, loader=loader)
    assert loader.calls == []


def test_last_close_is_required():
    with pytest.raises(TypeError, match="last_close"):
        pn.load_panel("KRAKEN", "1d")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        pn.load_panel("KRAKEN", "1d", None, CUT)  # type: ignore[misc]


def test_fewer_than_two_common_closes_raise():
    idx = grid("2023-01-02", "2023-01-08")
    btc = make_bars(idx[[0, 2, 4, 6]], 50.0)
    eth = make_bars(idx[[1, 3, 5, 6]], 5.0)
    with pytest.raises(ValueError, match="fewer than 2 closes where both"):
        pn.load_panel(last_close="2023-01-08", loader=kraken(btc, eth))
    with pytest.raises(ValueError, match="fewer than 2 closes where both"):  # only one in the windows
        pn.load_panel(
            last_close="2017-01-02",
            loader=kraken(
                make_bars(grid("2016-12-30", "2017-01-02"), 50.0),
                make_bars(grid("2016-12-30", "2017-01-02"), 5.0),
            ),
        )


# ------------------------------------------------------------------------------------------ a loader breaking the request


def _one_bad(bad_btc: pd.DataFrame, attrs: dict | None = None):
    good = make_bars(grid("2023-01-02", "2023-01-10"), 5.0)

    def loader(instrument, interval, start, end, catalog_dir):
        out = (bad_btc if instrument == "BTC/USD.KRAKEN" else good).copy()
        out.attrs = {"snapshot_id": SID} if attrs is None or instrument != "BTC/USD.KRAKEN" else attrs
        return out

    return loader


@pytest.mark.parametrize(
    "bad, attrs, match",
    [
        # a close before start, then one after last_close
        (make_bars(grid("2023-01-01", "2023-01-10"), 50.0), None, "outside the requested"),
        (make_bars(grid("2023-01-02", "2023-01-11"), 50.0), None, "outside the requested"),
        (make_bars(grid("2023-01-02 12:00", "2023-01-09 12:00"), 50.0), None, "off the 1 days"),
        (make_bars(grid("2023-01-02", "2023-01-10"), 50.0), {}, "no snapshot_id"),
        (make_bars(grid("2023-01-02", "2023-01-10"), 50.0), {"snapshot_id": ""}, "no snapshot_id"),
        (
            make_bars(grid("2023-01-02", "2023-01-10"), 50.0),
            {"snapshot_id": "fedcba9876543210"},
            "different snapshots",
        ),
        (
            make_bars(grid("2023-01-02", "2023-01-10"), 50.0),
            {"snapshot_id": SID, "bar_type": "BTC/USD.KRAKEN-1-HOUR-LAST-EXTERNAL"},
            "bar_type",
        ),
        (
            make_bars(grid("2023-01-02", "2023-01-10"), 50.0),
            {"snapshot_id": SID, "instrument": "ETH/USD.KRAKEN"},
            "instrument",
        ),
    ],
)
def test_a_loader_breaking_the_request_is_refused(bad, attrs, match):
    with pytest.raises(ValueError, match=match):
        pn.load_panel(start="2023-01-02", last_close="2023-01-10", loader=_one_bad(bad, attrs))


def test_matching_loader_attrs_are_accepted():
    ok = make_bars(grid("2023-01-02", "2023-01-10"), 50.0)
    attrs = {
        "snapshot_id": SID,
        "bar_type": "BTC/USD.KRAKEN-1-DAY-LAST-EXTERNAL",
        "instrument": "BTC/USD.KRAKEN",
    }
    panel = pn.load_panel(start="2023-01-02", last_close="2023-01-10", loader=_one_bad(ok, attrs))
    assert len(panel) == 9


def test_invalid_bars_and_indexes_are_refused():
    idx = grid("2023-01-02", "2023-01-10")
    nan = make_bars(idx, 50.0)
    nan.iloc[4, 3] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        pn.load_panel(last_close="2023-01-10", loader=_one_bad(nan))
    unsorted = make_bars(idx, 50.0).iloc[[0, 2, 1, 3]]
    with pytest.raises(ValueError, match="strictly increasing"):
        pn.load_panel(last_close="2023-01-10", loader=_one_bad(unsorted))
    naive = make_bars(idx, 50.0)
    naive.index = naive.index.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware close times"):
        pn.load_panel(last_close="2023-01-10", loader=_one_bad(naive))
    with pytest.raises(ValueError, match="tz-aware close times"):
        pn.load_panel(last_close="2023-01-10", loader=_one_bad(make_bars(idx, 50.0).reset_index(drop=True)))
    with pytest.raises(ValueError, match="tz-aware close times"):
        pn.load_panel(last_close="2023-01-10", loader=lambda *a, **k: None)
    paris = make_bars(idx, 50.0)
    paris.index = paris.index.tz_convert("Europe/Paris")
    with pytest.raises(ValueError, match="UTC"):
        pn.load_panel(last_close="2023-01-10", loader=_one_bad(paris))


# ------------------------------------------------------------------------------------------ alignment


def test_alignment_by_hand():
    """BTC misses 01-04; ETH misses 01-06 and 01-07; neither has 01-09. Nothing is filled."""
    days = grid("2023-01-02", "2023-01-11")
    btc = make_bars(without(days, "2023-01-04", "2023-01-09"), 20000.0)
    eth = make_bars(without(days, "2023-01-06", "2023-01-07", "2023-01-09"), 1500.0)
    panel = pn.load_panel(last_close="2023-01-11", loader=kraken(btc, eth))
    keep = pd.DatetimeIndex(
        [
            pd.Timestamp(d, tz="UTC")
            for d in ("2023-01-02", "2023-01-03", "2023-01-05", "2023-01-08", "2023-01-10", "2023-01-11")
        ],
        name="ts",
    ).as_unit("us")
    assert panel.index.equals(keep)
    for asset, src in (("BTC", btc), ("ETH", eth)):
        expected = src.loc[keep]
        expected.columns.name = "field"
        pd.testing.assert_frame_equal(panel[asset], expected, check_exact=True, check_freq=False)
    assert panel.attrs["alignment"] == {
        "rule": pn.ALIGNMENT_RULE,
        "request": {"start": None, "last_close": "2023-01-11T00:00:00+00:00"},
        "rows": {"BTC": 8, "ETH": 7},
        "common": 6,
        "first": "2023-01-02T00:00:00+00:00",
        "last": "2023-01-11T00:00:00+00:00",
        "dropped": {
            "BTC": {"count": 2, "closes": ["2023-01-06T00:00:00+00:00", "2023-01-07T00:00:00+00:00"]},
            "ETH": {"count": 1, "closes": ["2023-01-04T00:00:00+00:00"]},
        },
        "missing": {
            "count": 4,
            "closes": [
                "2023-01-04T00:00:00+00:00",
                "2023-01-06T00:00:00+00:00",
                "2023-01-07T00:00:00+00:00",
                "2023-01-09T00:00:00+00:00",
            ],
        },
    }
    assert not panel.isna().any().any()


def test_alignment_drops_a_late_start_and_an_early_end():
    """ETH starts two days after BTC and ends one day before: those BTC bars are dropped and listed, and they
    are not 'missing' (outside the panel's span)."""
    days = grid("2023-01-02", "2023-01-09")
    btc, eth = make_bars(days, 20000.0), make_bars(days[2:-1], 1500.0)
    al = pn.load_panel(last_close="2023-01-09", loader=kraken(btc, eth)).attrs["alignment"]
    assert al["dropped"]["BTC"] == {
        "count": 3,
        "closes": ["2023-01-02T00:00:00+00:00", "2023-01-03T00:00:00+00:00", "2023-01-09T00:00:00+00:00"],
    }
    assert al["dropped"]["ETH"] == {"count": 0, "closes": []}
    assert al["missing"] == {"count": 0, "closes": []} and al["common"] == 5
    assert (al["first"], al["last"]) == ("2023-01-04T00:00:00+00:00", "2023-01-08T00:00:00+00:00")


def test_hourly_alignment_by_hand():
    hours = grid("2023-03-01 01:00", "2023-03-01 08:00", "h")
    btc = make_bars(without(hours, "2023-03-01 03:00"), 20000.0)
    eth = make_bars(without(hours, "2023-03-01 03:00", "2023-03-01 05:00"), 1500.0)
    panel = pn.load_panel("KRAKEN", "1h", last_close="2023-03-01 08:00", loader=kraken(btc, eth))
    al = panel.attrs["alignment"]
    assert len(panel) == 6 and al["dropped"]["BTC"]["closes"] == ["2023-03-01T05:00:00+00:00"]
    assert al["dropped"]["ETH"]["count"] == 0
    assert al["missing"]["closes"] == ["2023-03-01T03:00:00+00:00", "2023-03-01T05:00:00+00:00"]


N_DAYS = 30
FIRST = CUT - (N_DAYS - 1) * DAY  # the grid ends exactly at the last validate close


@given(
    btc_has=st.lists(st.booleans(), min_size=N_DAYS, max_size=N_DAYS),
    eth_has=st.lists(st.booleans(), min_size=N_DAYS, max_size=N_DAYS),
)
@example(btc_has=[True] * N_DAYS, eth_has=[True] * N_DAYS)
@example(btc_has=[True, False] * (N_DAYS // 2), eth_has=[False, True] * (N_DAYS // 2))
def test_alignment_equals_a_brute_force_join(btc_has, eth_has):
    days = grid(FIRST, CUT)
    btc_idx, eth_idx = days[np.array(btc_has)], days[np.array(eth_has)]
    btc, eth = make_bars(btc_idx, 20000.0), make_bars(eth_idx, 1500.0)
    common = [d for d in days if d in set(btc_idx) and d in set(eth_idx)]
    loader = kraken(btc, eth)
    if len(common) < 2 or len(btc_idx) < 2 or len(eth_idx) < 2:
        with pytest.raises(ValueError):
            pn.load_panel(last_close=CUT, loader=loader)
        return
    panel = pn.load_panel(last_close=CUT, loader=loader)
    assert list(panel.index) == common
    for asset, src in (("BTC", btc), ("ETH", eth)):
        for d in common:  # every value is that asset's own bar at that close
            assert panel.loc[d, asset].tolist() == src.loc[d, FIELDS].tolist()
    al = panel.attrs["alignment"]
    iso = [d.isoformat() for d in days]
    assert al["dropped"]["BTC"]["closes"] == [iso[i] for i in range(N_DAYS) if btc_has[i] and not eth_has[i]]
    assert al["dropped"]["ETH"]["closes"] == [iso[i] for i in range(N_DAYS) if eth_has[i] and not btc_has[i]]
    for asset in ("BTC", "ETH"):
        assert al["dropped"][asset]["count"] == len(al["dropped"][asset]["closes"])
    span = [d for d in days if common[0] < d < common[-1] and d not in set(common)]
    assert al["missing"] == {"count": len(span), "closes": [d.isoformat() for d in span]}
    assert al["rows"] == {"BTC": int(sum(btc_has)), "ETH": int(sum(eth_has))}
    assert not panel.isna().any().any()


# ------------------------------------------------------------------------------------------ point in time


@given(
    btc_has=st.lists(st.booleans(), min_size=40, max_size=40),
    eth_has=st.lists(st.booleans(), min_size=40, max_size=40),
    cut_at=st.integers(0, 39),
    long_at=st.integers(0, 39),
)
@example(btc_has=[True] * 40, eth_has=[True] * 40, cut_at=1, long_at=39)
def test_a_shorter_load_equals_the_longer_load_cut_at_its_last_close(btc_has, eth_has, cut_at, long_at):
    """load_panel(last_close=E) == load_panel(last_close=E2 >= E) cut at E, and it never asks past E: rewriting
    every bar after E (here into the test window) changes nothing. Ends at the last validate close at most."""
    days = grid(CUT - 39 * DAY, CUT + 10 * DAY)  # the source reaches into the test window
    e, e2 = days[min(cut_at, long_at)], days[max(cut_at, long_at)]
    btc_idx, eth_idx = days[np.r_[btc_has, [True] * 10]], days[np.r_[eth_has, [True] * 10]]
    btc, eth = make_bars(btc_idx, 20000.0), make_bars(eth_idx, 1500.0)

    def load(last, b, x):
        loader = kraken(b, x)
        try:
            return pn.load_panel(last_close=last, loader=loader), loader.calls
        except ValueError as err:
            assert not isinstance(err, HoldoutWindowError)
            return None, loader.calls

    short, calls = load(e, btc, eth)
    assert [c[3] for c in calls] in ([e, e], [e], [])
    long, _ = load(e2, btc, eth)
    tampered_btc, tampered_eth = btc.copy(), eth.copy()
    for t in (tampered_btc, tampered_eth):
        later = t.index > e
        t.loc[later, ["open", "high", "low", "close"]] *= 1.37
        t.loc[later, "volume"] += 11.0
    again, _ = load(e, tampered_btc, tampered_eth)
    if short is None:
        assert again is None
        return
    pd.testing.assert_frame_equal(again, short, check_exact=True)
    assert again.attrs == short.attrs
    assert short.index[-1] <= e <= CUT
    assert long is not None
    cut_long = long.loc[long.index <= e]
    pd.testing.assert_frame_equal(short, cut_long, check_exact=True)
    al_s, al_l = short.attrs["alignment"], long.attrs["alignment"]
    for asset in ("BTC", "ETH"):
        assert al_s["dropped"][asset]["closes"] == [
            t for t in al_l["dropped"][asset]["closes"] if pd.Timestamp(t) <= e
        ]
    assert al_s["missing"]["closes"] == [
        t for t in al_l["missing"]["closes"] if pd.Timestamp(t) < short.index[-1]
    ]
    assert al_s["first"] == al_l["first"]
