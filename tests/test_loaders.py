"""Kraken OHLCVT and Binance kline loaders, epoch parsing and resampling (TESTING.md section 3).

CSV fixtures are written to ``tmp_path`` in the real layouts:
- Kraken OHLCVT, no header: ``timestamp,open,high,low,close,volume,trades`` (timestamp = bar OPEN, unix s)
- Binance kline: ``open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,
  taker_buy_quote_volume,ignore`` (ms, or us from 2025; close_time = open + interval - 1 unit)
The property tests build a clean set of bars, write it with every kind of mess the loaders must
handle (unit, header, order, stale duplicates, bad rows, bad "corrections"), and compare the loaded
frame with the clean set.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.data.loaders import (
    BINANCE_COLUMNS,
    KRAKEN_COLUMNS,
    epoch_to_ns,
    load_binance_klines,
    load_kraken_ohlcvt,
    resample,
)
from lab.runner.interface import validate_bars

UNIT = {"s": 1, "ms": 1_000, "us": 1_000_000}
OUT_COLUMNS = ["open", "high", "low", "close", "volume", "trades"]


def write_csv(path, lines):
    path.write_text("".join(f"{line}\n" for line in lines))
    return path


def utc(*args):
    return pd.Timestamp(*args, tz="UTC")


def frame(rows, index):
    """Expected loader output from (open, high, low, close, volume, trades) tuples."""
    return pd.DataFrame(rows, columns=OUT_COLUMNS, index=pd.DatetimeIndex(index, name="ts"), dtype=float)


def kraken_line(open_s, bar, unit="s"):
    o, h, lo, c, v, n = bar
    return f"{open_s * UNIT[unit]},{o!r},{h!r},{lo!r},{c!r},{v!r},{n}"


def binance_line(open_s, interval_s, bar, unit="ms"):
    o, h, lo, c, v, n = bar
    k = UNIT[unit]
    return (
        f"{open_s * k},{o!r},{h!r},{lo!r},{c!r},{v!r},{(open_s + interval_s) * k - 1},"
        f"{v * c!r},{n},{v / 2!r},{v * c / 2!r},0"
    )


# ---------------------------------------------------------------- Kraken: known file

DAY = 86_400
JAN1 = 1_609_459_200  # 2021-01-01 00:00 UTC
KRAKEN_BARS = [
    (29000.0, 29600.0, 28800.0, 29400.0, 120.5, 3500),
    (29400.0, 33000.0, 29000.0, 32100.0, 250.0, 8000),
    (32100.0, 34800.0, 31800.0, 33000.0, 300.0, 9000),
]
KRAKEN_EXPECTED = frame(KRAKEN_BARS, [utc("2021-01-02"), utc("2021-01-03"), utc("2021-01-04")])


@pytest.mark.parametrize("unit", ["s", "ms", "us"])
def test_kraken_daily_file(tmp_path, unit):
    lines = [kraken_line(JAN1 + i * DAY, bar, unit) for i, bar in enumerate(KRAKEN_BARS)]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)
    assert str(got.index.tz) == "UTC" and got.index.name == "ts"
    validate_bars(got)
    assert got.attrs == {
        "source": "XBTUSD_1440.csv",
        "rows_read": 3,
        "dropped_bad": 0,
        "dropped_duplicates": 0,
    }


def test_kraken_header_is_skipped(tmp_path):
    lines = [",".join(KRAKEN_COLUMNS)] + [
        kraken_line(JAN1 + i * DAY, bar) for i, bar in enumerate(KRAKEN_BARS)
    ]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)
    assert got.attrs["rows_read"] == 3


def test_kraken_hourly_file_name(tmp_path):
    lines = [kraken_line(JAN1 + i * 3600, bar) for i, bar in enumerate(KRAKEN_BARS)]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "xbtusd_60.CSV", lines))  # suffix match ignores case
    assert list(got.index) == [utc("2021-01-01 01:00"), utc("2021-01-01 02:00"), utc("2021-01-01 03:00")]


def test_kraken_interval_from_median_spacing(tmp_path):
    # hourly bars with one missing hour (Kraken skips intervals without trades): the median is 1 hour
    opens = [JAN1, JAN1 + 3600, JAN1 + 3 * 3600, JAN1 + 4 * 3600]
    bars = [*KRAKEN_BARS, KRAKEN_BARS[0]]
    lines = [kraken_line(t, b) for t, b in zip(opens, bars, strict=True)]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "prices.csv", lines))
    assert list(got.index) == [pd.Timestamp(t + 3600, unit="s", tz="UTC") for t in opens]


@pytest.mark.parametrize("interval", [60, "1h", pd.Timedelta(hours=1)])
def test_kraken_explicit_interval(tmp_path, interval):
    lines = [kraken_line(JAN1 + i * 3600, bar) for i, bar in enumerate(KRAKEN_BARS)]
    # the explicit interval wins over the file name
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines), interval=interval)
    assert got.index[0] == utc("2021-01-01 01:00")


def test_kraken_interval_errors(tmp_path):
    one = write_csv(tmp_path / "one.csv", [kraken_line(JAN1, KRAKEN_BARS[0])])
    with pytest.raises(ValueError, match="cannot infer the bar interval"):
        load_kraken_ohlcvt(one)
    assert load_kraken_ohlcvt(one, interval=1440).index[0] == utc("2021-01-02")
    with pytest.raises(ValueError, match="bar interval must be positive"):
        load_kraken_ohlcvt(one, interval=0)


def test_kraken_file_without_trades_column(tmp_path):
    lines = [kraken_line(JAN1 + i * DAY, bar).rsplit(",", 1)[0] for i, bar in enumerate(KRAKEN_BARS)]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(
        got.drop(columns="trades"), KRAKEN_EXPECTED.drop(columns="trades"), check_freq=False
    )
    assert got["trades"].isna().all()


def test_kraken_duplicates_keep_the_last_row(tmp_path):
    stale = (1.0, 2.0, 0.5, 1.5, 7.0, 1)
    lines = [kraken_line(JAN1 + DAY, stale)] + [
        kraken_line(JAN1 + i * DAY, b) for i, b in enumerate(KRAKEN_BARS)
    ]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)
    assert got.attrs["dropped_duplicates"] == 1


def test_kraken_unsorted_rows_are_sorted(tmp_path):
    lines = [kraken_line(JAN1 + i * DAY, b) for i, b in enumerate(KRAKEN_BARS)][::-1]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)


# The time and OHLCV fields of a bad row; each source appends its own remaining fields.
BAD_ROWS = [
    "{t},0,2,0.5,1,10",  # zero open
    "{t},1,2,0.5,-1,10",  # negative close
    "{t},1,0.5,2,1,10",  # high < low
    "{t},1,2,0.5,3,10",  # close above high
    "{t},0.4,2,0.5,1,10",  # open below low
    "{t},1,2,0.5,1,-10",  # negative volume
    "{t},abc,2,0.5,1,10",  # not a number
    "{t},,2,0.5,1,10",  # missing field
    "{t},1,2",  # short line
    "x{t},1,2,0.5,1,10",  # timestamp not a number
    "{t}.5,1,2,0.5,1,10",  # fractional timestamp
]


def kraken_bad(row, open_s):
    return row.format(t=open_s) + ",5"


def binance_bad(row, open_s, interval_s):
    return row.format(t=open_s * 1000) + f",{(open_s + interval_s) * 1000 - 1},0,5,0,0,0"


@pytest.mark.parametrize("bad", BAD_ROWS)
def test_kraken_bad_rows_are_dropped(tmp_path, bad):
    good = [kraken_line(JAN1 + i * DAY, b) for i, b in enumerate(KRAKEN_BARS)]
    # a bad row at a new time, and a bad "correction" of an existing row after it: neither survives
    lines = good + [kraken_bad(bad, JAN1 + 9 * DAY), kraken_bad(bad, JAN1 + DAY)]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)
    assert got.attrs["dropped_bad"] == 2 and got.attrs["rows_read"] == 5


@pytest.mark.parametrize("bad", BAD_ROWS)
def test_binance_bad_rows_are_dropped(tmp_path, bad):
    good = [binance_line(JAN1 + i * DAY, DAY, b) for i, b in enumerate(KRAKEN_BARS)]
    lines = good + [binance_bad(bad, JAN1 + 9 * DAY, DAY), binance_bad(bad, JAN1 + DAY, DAY)]
    got = load_binance_klines(write_csv(tmp_path / "BTCUSDT-1d.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)
    assert got.attrs["dropped_bad"] == 2 and got.attrs["rows_read"] == 5


def test_lines_with_extra_fields_are_skipped(tmp_path):
    good = [kraken_line(JAN1 + i * DAY, b) for i, b in enumerate(KRAKEN_BARS)]
    lines = good[:1] + [kraken_line(JAN1 + 5 * DAY, KRAKEN_BARS[0]) + ",999"] + good[1:]
    got = load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)


def test_unreadable_files(tmp_path):
    with pytest.raises(ValueError, match="file is empty"):
        load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", []))
    with pytest.raises(ValueError, match="no valid rows"):
        load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", [",".join(KRAKEN_COLUMNS)]))
    with pytest.raises(ValueError, match="no valid rows"):
        load_kraken_ohlcvt(write_csv(tmp_path / "prices.csv", [kraken_bad(BAD_ROWS[0], JAN1)]))
    with pytest.raises(ValueError, match="expected at least 6 columns, found 5"):
        load_kraken_ohlcvt(write_csv(tmp_path / "XBTUSD_1440.csv", [f"{JAN1},1,2,0.5,1"]))
    with pytest.raises(ValueError, match="expected at least 7 columns, found 6"):
        load_binance_klines(write_csv(tmp_path / "k.csv", [f"{JAN1}000,1,2,0.5,1,5"]))
    with pytest.raises(ValueError, match="no valid rows"):
        load_binance_klines(write_csv(tmp_path / "k.csv", [",".join(BINANCE_COLUMNS)]))


# ---------------------------------------------------------------- Binance: known file


@pytest.mark.parametrize("unit", ["s", "ms", "us"])
@pytest.mark.parametrize("header", [False, True])
def test_binance_daily_klines(tmp_path, unit, header):
    lines = [binance_line(JAN1 + i * DAY, DAY, bar, unit) for i, bar in enumerate(KRAKEN_BARS)]
    if header:
        lines.insert(0, ",".join(BINANCE_COLUMNS))
    got = load_binance_klines(write_csv(tmp_path / "BTCUSDT-1d-2021-01.csv", lines))
    pd.testing.assert_frame_equal(got, KRAKEN_EXPECTED, check_freq=False)
    validate_bars(got)
    assert got.attrs["rows_read"] == 3


def test_binance_mixed_ms_and_us_rows(tmp_path):
    """Binance spot files switched to microseconds on 2025-01-01; a concatenated file mixes units."""
    dec31 = int(utc("2024-12-31").timestamp())
    lines = [
        binance_line(dec31, DAY, KRAKEN_BARS[0], "ms"),
        binance_line(dec31 + DAY, DAY, KRAKEN_BARS[1], "us"),
    ]
    got = load_binance_klines(write_csv(tmp_path / "BTCUSDT-1d.csv", lines))
    assert list(got.index) == [utc("2025-01-01"), utc("2025-01-02")]


def test_binance_microsecond_timestamps_are_exact(tmp_path):
    t = 1_735_689_600_123_456  # us, 2025-01-01 00:00:00.123456: too many digits for a float round trip of ns
    line = f"{t},1,2,0.5,1.5,10,{t + 3_600_000_000 - 1},15,3,5,7,0"
    got = load_binance_klines(write_csv(tmp_path / "k.csv", [line]))
    assert got.index[0] == pd.Timestamp(t * 1000 + 3_600 * 10**9, unit="ns", tz="UTC")
    assert got.index[0].value % 1000 == 0 and got.index[0].microsecond == 123456


def test_binance_close_time_as_exact_bar_end(tmp_path):
    lines = [
        f"{(JAN1 + i * DAY) * 1000},1,2,0.5,1.5,10,{(JAN1 + (i + 1) * DAY) * 1000},15,3,5,7,0"
        for i in range(2)
    ]
    got = load_binance_klines(write_csv(tmp_path / "k.csv", lines))
    assert list(got.index) == [utc("2021-01-02"), utc("2021-01-03")]


def test_binance_bad_close_time_and_missing_count(tmp_path):
    good = f"{JAN1 * 1000},1,2,0.5,1.5,10,{(JAN1 + DAY) * 1000 - 1}"
    lines = [
        good,
        f"{(JAN1 + DAY) * 1000},1,2,0.5,1.5,10,{(JAN1 + DAY) * 1000}",  # close_time == open_time
        f"{(JAN1 + 2 * DAY) * 1000},1,2,0.5,1.5,10,{(JAN1 + DAY) * 1000}",  # close before open
        f"{(JAN1 + 3 * DAY) * 1000},1,2,0.5,1.5,10,x",  # close_time not a number
    ]
    got = load_binance_klines(write_csv(tmp_path / "k.csv", lines))  # 7 columns: no count
    assert list(got.index) == [utc("2021-01-02")]
    assert got["trades"].isna().all()
    assert got.attrs["dropped_bad"] == 3


# ---------------------------------------------------------------- epoch parsing


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1609459200", "2021-01-01"),
        ("1609459200000", "2021-01-01"),
        ("1609459200000000", "2021-01-01"),
        ("1609459200000000000", "2021-01-01"),
        ("1609459200123", "2021-01-01 00:00:00.123"),
        ("1609459200123456", "2021-01-01 00:00:00.123456"),
        ("  1609459200 ", "2021-01-01"),
        ("0", "1970-01-01"),
        ("9200000000", "2261-07-15 11:33:20"),  # latest second accepted
        ("9200000001", None),  # seconds past this would overflow nanoseconds
        ("9200000000000000000", None),
        ("99999999999999999999", None),
        ("-5", None),
        ("1.5", None),
        ("1e9", None),
        ("abc", None),
        (None, None),
    ],
)
def test_epoch_to_ns(text, expected):
    got = epoch_to_ns(pd.Series([text], dtype="str")).iloc[0]
    if expected is None:
        assert got is pd.NA
    else:
        assert pd.Timestamp(int(got), unit="ns", tz="UTC") == utc(expected)


# ---------------------------------------------------------------- property: messy files load clean


ohlc = st.lists(st.floats(1e-3, 1e6, allow_nan=False), min_size=4, max_size=4).map(sorted)


@st.composite
def bar_values(draw):
    lo, a, b, hi = draw(ohlc)
    o, c = (a, b) if draw(st.booleans()) else (b, a)
    return (lo, hi, o, c, draw(st.floats(0.0, 1e7)), draw(st.integers(0, 10**6)))


@st.composite
def messy_files(draw):
    n = draw(st.integers(2, 20))
    interval_min = draw(st.sampled_from([1, 5, 60, 240, 1440]))
    start = draw(st.integers(1_400_000_000, 1_900_000_000)) // 60 * 60
    opens = [start + i * interval_min * 60 for i in range(n)]
    values = [draw(bar_values()) for _ in range(n)]
    bars = {t: (o, hi, lo, c, v, k) for t, (lo, hi, o, c, v, k) in zip(opens, values, strict=True)}
    order = draw(st.permutations(opens))
    stale = draw(st.lists(st.sampled_from(opens), max_size=5))
    stale_values = [draw(bar_values()) for _ in stale]
    bad = draw(st.lists(st.tuples(st.sampled_from(BAD_ROWS), st.booleans()), max_size=4))
    return {
        "interval_min": interval_min,
        "bars": bars,
        "order": order,
        "stale": [
            (t, (o, hi, lo, c, v, k)) for t, (lo, hi, o, c, v, k) in zip(stale, stale_values, strict=True)
        ],
        # each bad row reuses a real time (a bad "correction", written last) or a time no good row has
        "bad": [(row, opens[0] if reuse else opens[-1] + 7 * interval_min * 60) for row, reuse in bad],
        "header": draw(st.booleans()),
        "units": [draw(st.sampled_from(list(UNIT))) for _ in range(n + len(stale))],
    }


def expected_frame(case):
    step = case["interval_min"] * 60
    opens = sorted(case["bars"])
    return frame(
        [case["bars"][t] for t in opens], [pd.Timestamp(t + step, unit="s", tz="UTC") for t in opens]
    )


def check_attrs(got, case):
    assert got.attrs["rows_read"] == len(case["bars"]) + len(case["stale"]) + len(case["bad"])
    assert got.attrs["dropped_bad"] == len(case["bad"])
    assert got.attrs["dropped_duplicates"] == len(case["stale"])


@given(case=messy_files())
def test_kraken_property_messy_file_loads_clean(tmp_path_factory, case):
    units = iter(case["units"])
    lines = [",".join(KRAKEN_COLUMNS)] if case["header"] else []
    lines += [kraken_line(t, bar, next(units)) for t, bar in case["stale"]]  # stale rows come first ...
    lines += [kraken_line(t, case["bars"][t], next(units)) for t in case["order"]]  # ... then the real ones
    lines += [kraken_bad(row, t) for row, t in case["bad"]]
    path = write_csv(tmp_path_factory.mktemp("kraken") / f"XBTUSD_{case['interval_min']}.csv", lines)
    got = load_kraken_ohlcvt(path)
    pd.testing.assert_frame_equal(got, expected_frame(case), check_freq=False)
    check_attrs(got, case)
    validate_bars(got)


@given(case=messy_files())
def test_binance_property_messy_file_loads_clean(tmp_path_factory, case):
    step = case["interval_min"] * 60
    units = iter(case["units"])
    lines = [",".join(BINANCE_COLUMNS)] if case["header"] else []
    lines += [binance_line(t, step, bar, next(units)) for t, bar in case["stale"]]
    lines += [binance_line(t, step, case["bars"][t], next(units)) for t in case["order"]]
    lines += [binance_bad(row, t, step) for row, t in case["bad"]]
    got = load_binance_klines(write_csv(tmp_path_factory.mktemp("binance") / "klines.csv", lines))
    pd.testing.assert_frame_equal(got, expected_frame(case), check_freq=False)
    check_attrs(got, case)


# ---------------------------------------------------------------- resample


def hourly_bars(start_close, n, seed=0, trades=True):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    bars = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n)),
            "low": np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n)),
            "close": close,
            "volume": rng.uniform(1, 100, n),
        },
        index=pd.date_range(start_close, periods=n, freq="h", tz="UTC", name="ts"),
    )
    if trades:
        bars["trades"] = rng.integers(1, 50, n).astype(float)
    return bars


def aggregate(chunk: pd.DataFrame) -> list[float]:
    row = [
        chunk["open"].iloc[0],
        chunk["high"].max(),
        chunk["low"].min(),
        chunk["close"].iloc[-1],
        chunk["volume"].sum(),
    ]
    if "trades" in chunk:
        row.append(chunk["trades"].sum(min_count=1))
    return row


def test_resample_hourly_to_daily_known_answer():
    bars = hourly_bars("2024-01-01 01:00", 72)  # closes 01:00 Jan 1 .. 00:00 Jan 4: three full days
    got = resample(bars, "1D")
    assert list(got.index) == [utc("2024-01-02"), utc("2024-01-03"), utc("2024-01-04")]
    for day in range(3):
        np.testing.assert_allclose(got.iloc[day].to_numpy(), aggregate(bars.iloc[24 * day : 24 * (day + 1)]))
    validate_bars(got)
    assert got.index.name == "ts" and (got.dtypes == np.float64).all()


def test_resample_drops_incomplete_buckets():
    bars = hourly_bars("2024-01-01 05:00", 72)  # starts mid-day, ends at 04:00 Jan 4
    got = resample(bars, "1D")
    # the bucket ending Jan 2 started before the first bar opened; the bucket ending Jan 5 is unfinished
    assert list(got.index) == [utc("2024-01-03"), utc("2024-01-04")]
    np.testing.assert_allclose(
        got.iloc[0].to_numpy(), aggregate(bars.loc["2024-01-02 01:00":"2024-01-03 00:00"])
    )
    np.testing.assert_allclose(
        got.iloc[1].to_numpy(), aggregate(bars.loc["2024-01-03 01:00":"2024-01-04 00:00"])
    )


def test_resample_skips_empty_buckets_and_keeps_gappy_ones():
    bars = hourly_bars("2024-01-01 01:00", 96)
    no_day_2 = bars.drop(bars.loc["2024-01-02 01:00":"2024-01-03 00:00"].index)  # a whole day missing
    assert list(resample(no_day_2, "1D").index) == [utc("2024-01-02"), utc("2024-01-04"), utc("2024-01-05")]
    holes = bars.drop(bars.index[[30, 31, 40]])  # a few hours missing inside day 2: still one bar
    got = resample(holes, "1D")
    assert len(got) == 4
    np.testing.assert_allclose(
        got.loc[utc("2024-01-03")].to_numpy(), aggregate(holes.loc["2024-01-02 01:00":"2024-01-03 00:00"])
    )


def test_resample_trades():
    bars = hourly_bars("2024-01-01 01:00", 48)
    bars.loc[: utc("2024-01-02"), "trades"] = np.nan  # no trade counts on day 1
    got = resample(bars, "1D")
    assert np.isnan(got["trades"].iloc[0]) and got["trades"].iloc[1] == bars["trades"].iloc[24:].sum()
    plain = resample(bars.drop(columns="trades"), "1D")
    assert list(plain.columns) == ["open", "high", "low", "close", "volume"]


@given(
    start_hour=st.integers(0, 23),
    n=st.integers(2, 150),
    seed=st.integers(0, 2**32 - 1),
    rule=st.sampled_from(["1D", "4h", "6h"]),
    data=st.data(),
)
def test_resample_property(start_hour, n, seed, rule, data):
    bars = hourly_bars(utc("2024-03-01") + pd.Timedelta(hours=start_hour), n, seed)
    # gaps inside (ends kept); under a quarter of the bars go, so most spacings stay 1 hour and the
    # input bar length (median spacing) is 1 hour
    drop = data.draw(st.sets(st.integers(1, n - 2), max_size=(n - 2) // 4)) if n >= 3 else set()
    bars = bars.iloc[[i for i in range(n) if i not in drop]]
    assert pd.Series(bars.index).diff().median() == pd.Timedelta(hours=1)
    got = resample(bars, rule)
    width = pd.Timedelta(rule)
    first_open = bars.index[0] - pd.Timedelta(hours=1)
    # every complete bucket that has data is present, and nothing else
    labels = sorted({ts.ceil(width) for ts in bars.index})
    expected = [lab for lab in labels if lab - width >= first_open and lab <= bars.index[-1]]
    assert list(got.index) == expected
    for label in expected:
        chunk = bars[(bars.index > label - width) & (bars.index <= label)]
        np.testing.assert_allclose(got.loc[label].to_numpy(), aggregate(chunk), rtol=1e-12)
    if len(got) >= 2:
        validate_bars(got)


def test_resample_rejects_invalid_bars():
    bars = hourly_bars("2024-01-01 01:00", 30)
    bars.iloc[3, bars.columns.get_loc("close")] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        resample(bars, "1D")
