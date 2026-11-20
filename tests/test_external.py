"""lab/data/external.py: the positioning store and the point-in-time loader.

The guarantees: the row of a bar closing at t uses only values with known_at < t (tamper-the-future, and the exact
boundary); nothing is carried beyond the documented ages; nothing of the test window is stored or returned; a
store file changed after the build is refused. Every expected number is computed by hand here.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from lab.data import external as ext
from lab.data import futures as fu
from lab.data.sources import sha256_file

UTC = "UTC"
CUT = pd.Timestamp("2024-07-01", tz=UTC)  # config/splits.yaml: validate ends 2024-06-30
SID = "00000000000000aa"


def ts(values) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(values), utc=True, format="mixed")).as_unit("us")


def funding(times, rates, hours=8.0) -> pd.DataFrame:
    t = ts(times)
    return pd.DataFrame({"ts": t, "known_at": t, "rate": np.asarray(rates, dtype=float),
                         "interval_hours": np.broadcast_to(float(hours), len(t)).astype(float)})


def metrics(times, **values) -> pd.DataFrame:
    t = ts(times)
    out = pd.DataFrame({"ts": t, "known_at": (t + fu.METRICS_LAG).as_unit("us")})
    for name in fu.METRIC_FIELDS.values():
        out[name] = np.asarray(values.get(name, np.arange(1.0, len(t) + 1)), dtype=float)
    return out


def store(tmp_path, tables: dict[tuple[str, str], pd.DataFrame], sid=SID):
    entries = [ext.write_table(tmp_path, sym, name, f) for (sym, name), f in tables.items()]
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps({"snapshot_id": sid, "external": entries}))
    return entries


# ============================================================================ known answers


FUNDING_TIMES = ["2024-01-01 00:00:00.002", "2024-01-01 08:00", "2024-01-01 16:00", "2024-01-02 00:00",
                 "2024-01-02 08:00"]  # 2024-01-02 16:00 is missing
RATES = [0.0001, -0.0002, 0.0004, 0.0003, 0.0005]


def test_funding_known_answers():
    f = funding(FUNDING_TIMES, RATES)
    m = metrics(["2024-01-01 00:00"])
    closes = ts(["2024-01-01 00:00", "2024-01-01 08:00:00.000001", "2024-01-02 00:00", "2024-01-03 00:00",
                 "2024-01-02 16:05:00", "2024-01-02 16:05:00.000001"])
    got = ext.positioning_at(f, m, closes)
    # at 2024-01-01 00:00 nothing is known yet (the first rate is known 2 ms later)
    assert np.isnan(got["funding_last"].iloc[0]) and got["funding_count_1d"].iloc[0] == 0
    # one microsecond after 08:00 the 08:00 rate is known; the window holds 2 rates = 16 hours: no mean
    assert got["funding_last"].iloc[1] == -0.0002 and got["funding_count_1d"].iloc[1] == 2
    assert np.isnan(got["funding_mean_1d"].iloc[1])
    # the daily bar of 2024-01-01 closes 2024-01-02 00:00: the 00:00 rate of that instant is NOT in it
    assert got["funding_last"].iloc[2] == 0.0004 and got["funding_count_1d"].iloc[2] == 3
    assert got["funding_mean_1d"].iloc[2] == np.mean([0.0001, -0.0002, 0.0004])
    # 2024-01-03 00:00: the 16:00 rate is missing, so the newest (08:00) is 16 h old and the day incomplete
    assert np.isnan(got["funding_last"].iloc[3]) and got["funding_count_1d"].iloc[3] == 2
    assert np.isnan(got["funding_mean_1d"].iloc[3])
    # 8 h + 5 min after the 08:00 rate it still counts; one microsecond later it is too old
    assert got["funding_last"].iloc[4] == 0.0005 and np.isnan(got["funding_last"].iloc[5])
    assert got.index.name == "ts" and str(got.index.dtype) == "datetime64[us, UTC]"
    assert list(got.columns) == list(ext.OUTPUT_COLUMNS) and got["funding_count_1d"].dtype == np.int64


def test_funding_7d_mean_is_the_last_21_rates():
    times = pd.date_range("2024-01-01", "2024-01-08 16:00", freq="8h", tz=UTC)  # 24 rates, i = 3 * day + slot
    rates = np.arange(1.0, 25.0) * 1e-5
    f = funding([str(x) for x in times], rates)
    got = ext.positioning_at(f, metrics(["2024-01-01"]),
                             ts(["2024-01-08 00:00", "2024-01-09 00:00", "2024-01-09 00:00:00.000001"]))
    # at 2024-01-08 00:00 the window [01-01 00:00, 01-08 00:00) holds the first 21 rates (the 01-08 00:00 rate
    # is published at the close and counts from the next bar on)
    assert got["funding_count_7d"].iloc[0] == 21 and got["funding_mean_7d"].iloc[0] == rates[:21].mean()
    assert got["funding_count_7d"].iloc[1] == 21 and got["funding_mean_7d"].iloc[1] == rates[3:24].mean()
    assert got["funding_count_7d"].iloc[2] == 20 and np.isnan(got["funding_mean_7d"].iloc[2])  # 01-02 00:00 left
    short = ext.positioning_at(f.drop(index=10), metrics(["2024-01-01"]), ts(["2024-01-08 00:00"]))
    assert short["funding_count_7d"].iloc[0] == 20 and np.isnan(short["funding_mean_7d"].iloc[0])  # one missing


def test_funding_window_counts_hours_not_events():
    f = funding(["2024-01-01 00:00", "2024-01-01 04:00", "2024-01-01 08:00", "2024-01-01 12:00",
                 "2024-01-01 16:00", "2024-01-01 20:00"], [1e-4, 2e-4, 3e-4, 4e-4, 5e-4, 6e-4], hours=4.0)
    got = ext.positioning_at(f, metrics(["2024-01-01"]), ts(["2024-01-02 00:00", "2024-01-02 00:00:00.000001"]))
    assert got["funding_count_1d"].tolist() == [6, 5]  # [t - 1 day, t): the 00:00 rate leaves the window
    assert got["funding_mean_1d"].iloc[0] == np.mean([1e-4, 2e-4, 3e-4, 4e-4, 5e-4, 6e-4])
    assert np.isnan(got["funding_mean_1d"].iloc[1])  # 5 x 4 h = 20 h: incomplete


def test_metrics_known_answers():
    times = [str(t) for t in pd.date_range("2024-01-01 23:00", "2024-01-02 23:55", freq="5min", tz=UTC)]
    n = len(times)
    oi = 1000.0 + np.arange(n)
    acc = np.arange(n) / 100 + 1.0
    acc[-24:-1] = np.nan  # no long/short ratio stamped 22:00 .. 23:50 on 2024-01-02
    m = metrics(times, open_interest=oi, open_interest_value=oi * 50, account_ls_ratio=acc)
    f = funding(["2024-01-01 16:00"], [0.0001])
    closes = ts(["2024-01-02 00:00", "2024-01-03 00:00", "2024-01-03 00:00:00.000001", "2024-01-03 01:00",
                 "2024-01-03 01:00:00.000001"])
    got = ext.positioning_at(f, m, closes)
    i0 = times.index("2024-01-01 23:50:00+00:00")  # stamped 23:50, known 23:55 < 00:00
    assert got["oi_last"].iloc[0] == oi[i0] and got["oi_value_last"].iloc[0] == oi[i0] * 50
    i1 = times.index("2024-01-02 23:50:00+00:00")  # the 23:55 row is known only AT 00:00: not in that row
    assert got["oi_last"].iloc[1] == oi[i1] and got["oi_last"].iloc[2] == oi[-1]
    assert got["oi_change_1d"].iloc[1] == oi[i1] / oi[i0] - 1
    assert np.isnan(got["oi_change_7d"].iloc[1])  # nothing a week earlier
    # the newest ratio known before 00:00 is stamped 21:55 (known 22:00): 2 hours old, more than the 1-hour limit
    assert np.isnan(got["ls_account_last"].iloc[1]) and got["ls_account_last"].iloc[2] == acc[-1]
    # the 23:55 row (known 00:00) is exactly 1 hour old at 01:00 and too old one microsecond later
    assert got["oi_last"].iloc[3] == oi[-1] and got["ls_account_last"].iloc[3] == acc[-1]
    assert np.isnan(got["oi_last"].iloc[4]) and np.isnan(got["oi_change_1d"].iloc[4])


def test_metrics_values_expire_after_the_max_age():
    m = metrics(["2024-01-01 22:00", "2024-01-01 22:55"], open_interest=[1.0, 2.0], account_ls_ratio=[1.5, np.nan])
    got = ext.positioning_at(funding(["2024-01-01"], [0.0]), m,
                             ts(["2024-01-01 23:00", "2024-01-02 00:00", "2024-01-02 00:00:00.000001"]))
    assert got["ls_account_last"].iloc[0] == 1.5 and got["oi_last"].iloc[0] == 1.0  # 22:55 is known AT 23:00
    assert got["oi_last"].iloc[1] == 2.0  # known 23:00: exactly 1 hour old counts
    assert np.isnan(got["ls_account_last"].iloc[1])  # 22:05 is 1 h 55 min old; the 22:55 row has no ratio
    assert np.isnan(got["oi_last"].iloc[2])  # 1 hour and 1 microsecond: too old


def test_oi_change_by_hand():
    times = ["2024-01-01 23:50", "2024-01-02 23:50", "2024-01-08 23:50"]
    m = metrics(times, open_interest=[100.0, 110.0, 99.0])
    got = ext.positioning_at(funding(["2024-01-01"], [0.0]), m, ts(["2024-01-03", "2024-01-09"]))
    assert got["oi_change_1d"].iloc[0] == 110.0 / 100.0 - 1
    assert np.isnan(got["oi_change_1d"].iloc[1])  # 2024-01-08 00:00 has no value within the hour
    assert got["oi_change_7d"].iloc[1] == 99.0 / 100.0 - 1  # at 2024-01-02 00:00 the newest is the 01-01 23:50 row


# ============================================================================ tamper the future


def random_tables(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    f_times = pd.date_range("2024-01-01", "2024-01-04", freq="8h", tz=UTC)
    f_times = f_times[rng.random(len(f_times)) > 0.15]
    f_times = f_times + pd.to_timedelta(rng.integers(0, 50, len(f_times)), "ms")  # stamps a few ms late, as in the files
    f = funding([str(t) for t in f_times], rng.normal(1e-4, 3e-4, len(f_times)))
    m_times = pd.date_range("2024-01-01", "2024-01-04", freq="5min", tz=UTC)
    m_times = m_times[rng.random(len(m_times)) > 0.1]
    values = {name: rng.uniform(0.5, 2.0, len(m_times)) for name in fu.METRIC_FIELDS.values()}
    for v in values.values():
        v[rng.random(len(v)) < 0.1] = np.nan
    return f, metrics([str(t) for t in m_times], **values)


def tamper_from(table: pd.DataFrame, cut: pd.Timestamp, rng) -> pd.DataFrame:
    """Every row known at or after ``cut`` gets new values; some are dropped; a new row is added after ``cut``."""
    out = table.copy()
    late = (out["known_at"] >= cut).to_numpy()
    for col in out.columns[2:]:
        out.loc[late, col] = rng.uniform(-5, 5, late.sum())
    out = out.loc[~late | (rng.random(len(out)) > 0.3)]
    extra = out.iloc[-1:].copy()
    extra["ts"] = extra["known_at"] = pd.DatetimeIndex([cut]).as_unit("us")  # known exactly at the cut
    return pd.concat([out, extra]).drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


@example(seed=0, cut_minutes=1440, micros=0)  # a daily close: the 00:00 funding rate is published at the cut
@example(seed=1, cut_minutes=2880 + 5, micros=0)  # exactly when a metrics row becomes known
@given(seed=st.integers(0, 50), cut_minutes=st.integers(60, 4000), micros=st.integers(0, 299_999_999))
def test_a_value_known_at_or_after_a_close_never_appears_in_its_row(seed, cut_minutes, micros):
    """Tamper the future: rewrite, drop and add every value known at or after the cut; every row closing at or
    before the cut (on the hourly grid and at the cut itself) must be bit-identical."""
    f, m = random_tables(seed)
    cut = pd.Timestamp("2024-01-01", tz=UTC) + pd.Timedelta(minutes=cut_minutes) + pd.Timedelta(microseconds=micros)
    closes = pd.date_range(pd.Timestamp("2024-01-01 01:00", tz=UTC), cut, freq="1h").append(pd.DatetimeIndex([cut]))
    rng = np.random.default_rng(seed + 1)
    before = ext.positioning_at(f, m, closes)
    after = ext.positioning_at(tamper_from(f, cut, rng), tamper_from(m, cut, rng), closes)
    pd.testing.assert_frame_equal(before, after)


@given(seed=st.integers(0, 50), cut_minutes=st.integers(1500, 4000))
def test_the_newest_value_known_before_a_close_is_in_its_row(seed, cut_minutes):
    """Touch the present: changing the newest value known strictly before the close changes that close's row."""
    f, m = random_tables(seed)
    close = pd.Timestamp("2024-01-01", tz=UTC) + pd.Timedelta(minutes=cut_minutes)
    got = ext.positioning_at(f, m, ts([close]))
    for table, column, out_col in ((f, "rate", "funding_last"), (m, "open_interest", "oi_last")):
        valid = table[table[column].notna() & (table["known_at"] < close)]
        if np.isnan(got[out_col].iloc[0]):
            continue  # nothing fresh enough; covered by the known-answer tests
        newest = valid.index[-1]
        touched = table.copy()
        touched.loc[newest, column] = table.loc[newest, column] * 3 + 1
        f2, m2 = (touched, m) if table is f else (f, touched)
        assert ext.positioning_at(f2, m2, ts([close]))[out_col].iloc[0] != got[out_col].iloc[0]


def test_a_metrics_row_is_known_5_minutes_after_its_stamp():
    """In files from 2024-04-26 on, create_time T is the START of the 5-minute period: the row can only be used
    by a bar closing after T + 5 minutes. The daily bar closing at midnight never sees the 23:55 row."""
    m = metrics(["2024-06-29 23:50", "2024-06-29 23:55"], open_interest=[1.0, 2.0])
    f = funding(["2024-06-29 16:00"], [0.0])
    got = ext.positioning_at(f, m, ts(["2024-06-30 00:00", "2024-06-30 00:00:00.000001"]))
    assert got["oi_last"].tolist() == [1.0, 2.0]


# ============================================================================ the store


def test_store_round_trip_and_entry(tmp_path):
    f = funding(FUNDING_TIMES, RATES)
    entry = ext.write_table(tmp_path, "BTCUSDT", "funding", f)
    assert entry == {
        "symbol": "BTCUSDT", "table": "funding", "path": "ext/binance_futures/BTCUSDT/funding.parquet",
        "sha256": sha256_file(tmp_path / entry["path"]), "rows": 5,
        "first_ts": "2024-01-01T00:00:00.002000+00:00", "last_ts": "2024-01-02T08:00:00+00:00",
        "first_known_at": "2024-01-01T00:00:00.002000+00:00", "last_known_at": "2024-01-02T08:00:00+00:00",
    }
    back = ext.read_table(tmp_path, "BTCUSDT", "funding", sha256=entry["sha256"])
    pd.testing.assert_frame_equal(back, f)
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps({"snapshot_id": SID, "external": [entry]}))
    pd.testing.assert_frame_equal(ext.read_table(tmp_path, "BTCUSDT", "funding"), f)  # hash from SNAPSHOT.json


def test_store_refuses_bad_input(tmp_path):
    with pytest.raises(ValueError, match="symbol must be one of"):
        ext.table_path(tmp_path, "DOGEUSDT", "funding")
    with pytest.raises(ValueError, match="table one of"):
        ext.table_path(tmp_path, "BTCUSDT", "trades")
    with pytest.raises(ValueError, match="funding columns must be"):
        ext.write_table(tmp_path, "BTCUSDT", "funding", funding(["2024-01-01"], [0.0]).drop(columns="known_at"))


def test_a_store_file_changed_after_the_build_is_refused(tmp_path):
    store(tmp_path, {("BTCUSDT", "funding"): funding(FUNDING_TIMES, RATES)})
    path = ext.table_path(tmp_path, "BTCUSDT", "funding")
    changed = funding(FUNDING_TIMES, [*RATES[:-1], 0.01])
    changed.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="SHA-256 does not match the snapshot"):
        ext.read_table(tmp_path, "BTCUSDT", "funding")
    with pytest.raises(FileNotFoundError, match="lists no ETHUSDT funding table"):
        ext.read_table(tmp_path, "ETHUSDT", "funding")


@pytest.mark.parametrize(
    "bad, match",
    [
        (funding(FUNDING_TIMES, RATES).rename(columns={"rate": "r"}), "columns"),
        (funding(FUNDING_TIMES[::-1], RATES), "not strictly increasing"),
        (funding([FUNDING_TIMES[0]] * 2, RATES[:2]), "not strictly increasing"),
    ],
)
def test_read_table_checks_the_layout(tmp_path, bad, match):
    path = ext.table_path(tmp_path, "BTCUSDT", "funding")
    path.parent.mkdir(parents=True)
    bad.to_parquet(path, index=False)
    with pytest.raises(ValueError, match=match):
        ext.read_table(tmp_path, "BTCUSDT", "funding", sha256=sha256_file(path))


def test_a_store_with_test_window_values_is_refused(tmp_path):
    late = funding(["2024-06-30 16:00", "2024-07-01 00:00"], [0.0001, 0.0002])  # the second is known AT the cut
    store(tmp_path, {("BTCUSDT", "funding"): late, ("BTCUSDT", "metrics"): metrics(["2024-06-30 23:00"])})
    assert ext.holdout_cut() == CUT
    with pytest.raises(ext.HoldoutWindowError, match="known at or after 2024-07-01T00:00:00"):
        ext.read_table(tmp_path, "BTCUSDT", "funding")
    with pytest.raises(ext.HoldoutWindowError):
        ext.load_positioning("BTCUSDT", end="2024-06-01", catalog_dir=tmp_path)


# ============================================================================ load_positioning


@pytest.fixture
def catalog(tmp_path):
    f = funding([str(t) for t in pd.date_range("2024-06-20", "2024-06-30 16:00", freq="8h", tz=UTC)],
                np.linspace(-1e-4, 3e-4, 33))
    times = pd.date_range("2024-06-27 00:00", "2024-06-30 23:50", freq="5min", tz=UTC)
    m = metrics([str(t) for t in times], open_interest=1000.0 + np.arange(len(times)))
    store(tmp_path, {("BTCUSDT", "funding"): f, ("BTCUSDT", "metrics"): m})
    return tmp_path, f, m


def test_load_positioning_daily_defaults_stop_at_the_cut(catalog):
    root, f, m = catalog
    got = ext.load_positioning("BTCUSDT", catalog_dir=root)
    assert got.index[0] == pd.Timestamp("2024-06-21", tz=UTC) and got.index[-1] == CUT and len(got) == 11
    pd.testing.assert_frame_equal(got, ext.positioning_at(f, m, got.index))
    assert got.attrs == {"snapshot_id": SID, "symbol": "BTCUSDT", "freq": "1d", "cut": CUT.isoformat(),
                         "rules": ext.RULES}
    last = got.iloc[-1]
    assert last["oi_last"] == m["open_interest"].iloc[-1]  # stamped 23:50 on the last validate day
    assert last["funding_last"] == f["rate"].iloc[-1] and last["funding_count_1d"] == 3
    assert np.isnan(got["oi_last"].iloc[0])  # metrics start later than funding


def test_load_positioning_hourly_and_bounds(catalog):
    root, f, m = catalog
    got = ext.load_positioning("BTCUSDT", "1h", start="2024-06-30 10:30", end=CUT, catalog_dir=root)
    assert got.index[0] == pd.Timestamp("2024-06-30 11:00", tz=UTC) and got.index[-1] == CUT and len(got) == 14
    naive = ext.load_positioning("BTCUSDT", "1h", start="2024-06-30 11:00", end="2024-06-30 13:59", catalog_dir=root)
    assert naive.index.tolist() == list(pd.date_range("2024-06-30 11:00", periods=3, freq="1h", tz=UTC))
    aware = ext.load_positioning("BTCUSDT", "1h", start=pd.Timestamp("2024-06-30 13:00+02:00"),
                                 end=pd.Timestamp("2024-06-30 14:00+02:00"), catalog_dir=root)
    assert aware.index.tolist() == [pd.Timestamp("2024-06-30 11:00", tz=UTC), pd.Timestamp("2024-06-30 12:00", tz=UTC)]


@pytest.mark.parametrize("end", ["2024-07-01 00:00:00.000001", "2024-07-01 01:00", "2025-01-01",
                                 pd.Timestamp("2024-07-01 02:00+02:00") + pd.Timedelta(microseconds=1)])
def test_load_positioning_refuses_the_test_window(catalog, end):
    root, _, _ = catalog
    with pytest.raises(ext.HoldoutWindowError, match="close of the last validate bar"):
        ext.load_positioning("BTCUSDT", "1h", end=end, catalog_dir=root)


def test_load_positioning_argument_errors(catalog):
    root, _, _ = catalog
    with pytest.raises(ValueError, match="symbol must be one of"):
        ext.load_positioning("BTC", catalog_dir=root)
    with pytest.raises(ValueError, match="freq one of"):
        ext.load_positioning("BTCUSDT", "15m", catalog_dir=root)
    with pytest.raises(ValueError, match="no 1d close between"):
        ext.load_positioning("BTCUSDT", start="2024-06-29 01:00", end="2024-06-29 23:00", catalog_dir=root)
