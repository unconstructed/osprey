"""lab/data/futures.py: Binance USD-M futures files (funding, metrics, 5-minute klines) parsed, cleaned, checked,
and the timing check that decides when a metrics row is known. No network: every zip is built here."""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lab.data import futures as fu

M5 = pd.Timedelta(minutes=5)
HEADER_M = ",".join(fu.METRICS_HEADER)
HEADER_F = ",".join(fu.FUNDING_HEADER)


def zip_csv(path: Path, lines: list[str], member: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member or path.stem + ".csv", "\n".join(lines) + "\n")
    return path


def ms(ts: str) -> int:
    return int(pd.Timestamp(ts, tz="UTC").value // 1_000_000)


def metrics_line(ts: str, oi="100.5", value="2000.0", a="1.1", b="1.2", c="1.3", d="0.9", sym="BTCUSDT") -> str:
    return f"{ts},{sym},{oi},{value},{a},{b},{c},{d}"


# ============================================================================ reading


def test_describe():
    assert fu.describe(pd.Timedelta(minutes=5)) == "5 min"
    assert fu.describe(pd.Timedelta(hours=1)) == "1 h" and fu.describe(pd.Timedelta(hours=2)) == "2 h"
    assert fu.describe(pd.Timedelta(minutes=90)) == "90 min" and fu.describe(pd.Timedelta(0)) == "0 min"


def test_read_zip_rows_header_width_and_quotes(tmp_path):
    p = zip_csv(tmp_path / "X-fundingRate-2024-01.zip", [HEADER_F, "1,8,0.1", '2,"8",""', "3,8", "4,8,0.1,9"])
    raw, info = fu.read_zip_rows(p, fu.FUNDING_HEADER)
    assert raw.values.tolist() == [["1", "8", "0.1"], ["2", "8", ""]]  # quotes stripped: "" is an empty field
    assert info == {"rows_read": 4, "bad_width": 2}
    p2 = zip_csv(tmp_path / "Y-fundingRate-2024-01.zip", ["1,8,0.1"])  # no header (older files)
    assert fu.read_zip_rows(p2, fu.FUNDING_HEADER)[0].values.tolist() == [["1", "8", "0.1"]]
    p3 = zip_csv(tmp_path / "Z-fundingRate-2024-01.zip", [])
    raw3, info3 = fu.read_zip_rows(p3, fu.FUNDING_HEADER)
    assert raw3.empty and list(raw3.columns) == list(fu.FUNDING_HEADER) and info3 == {"rows_read": 0, "bad_width": 0}


def test_read_zip_rows_refuses_other_layouts(tmp_path):
    with pytest.raises(ValueError, match=r"expected one member X-metrics-2024-01-01\.csv, found \['other\.csv'\]"):
        fu.read_zip_rows(zip_csv(tmp_path / "X-metrics-2024-01-01.zip", [HEADER_M], "other.csv"), fu.METRICS_HEADER)
    with pytest.raises(ValueError, match="unexpected header 'create_time,symbol,open_interest'"):
        fu.read_zip_rows(zip_csv(tmp_path / "Y-metrics-2024-01-01.zip", ["create_time,symbol,open_interest"]),
                         fu.METRICS_HEADER)


def test_load_funding_known_answer_and_cleaning(tmp_path):
    jan = zip_csv(tmp_path / "BTCUSDT-fundingRate-2024-01.zip", [
        HEADER_F,
        f"{ms('2024-01-01 08:00')},8,0.0001",
        f"{ms('2024-01-01 00:00') + 2},8,-0.00012359",  # 2 ms after the hour, out of order
        f"{ms('2024-01-01 16:00')},8,abc",  # bad rate
        f"{ms('2024-01-01 16:00')},0,0.0001",  # bad interval
        "x,8,0.0001",  # bad time
        f"{ms('2024-02-01 00:00')},8,0.0003",  # next month in a January file: kept and counted
    ])
    feb = zip_csv(tmp_path / "BTCUSDT-fundingRate-2024-02.zip", [
        f"{ms('2024-02-01 00:00')},8,0.0003",  # exact duplicate
        f"{ms('2024-01-01 08:00')},8,0.0002",  # conflicting duplicate: the later file wins
    ])
    f = fu.load_funding([jan, feb])
    assert [t.isoformat() for t in f["ts"]] == [
        "2024-01-01T00:00:00.002000+00:00", "2024-01-01T08:00:00+00:00", "2024-02-01T00:00:00+00:00"]
    assert f["rate"].tolist() == [-0.00012359, 0.0002, 0.0003] and f["interval_hours"].tolist() == [8.0] * 3
    assert str(f["ts"].dtype) == "datetime64[us, UTC]"
    assert f.attrs == {"files": 2, "rows_read": 8, "dropped_bad": 3, "files_out_of_order": 2,
                       "rows_outside_file_period": 2, "exact_duplicates": 1, "conflicting_duplicates": 1,
                       "conflicting_examples": ["2024-01-01T08:00:00+00:00"]}


def test_load_funding_without_valid_rows_raises(tmp_path):
    with pytest.raises(ValueError, match="no valid rows"):
        fu.load_funding([zip_csv(tmp_path / "BTCUSDT-fundingRate-2024-01.zip", ["x,8,0.1"])])
    with pytest.raises(ValueError, match="no valid rows"):
        fu.load_funding([])


def test_load_metrics_known_answer_and_cleaning(tmp_path):
    day = zip_csv(tmp_path / "BTCUSDT-metrics-2024-01-01.zip", [
        HEADER_M,
        metrics_line("2024-01-01 00:05:00"),
        metrics_line("2024-01-01 00:00:00", a='""', b="", c="0E-8", d="inf"),  # empty, empty, placeholder, inf
        metrics_line("2024-01-01 00:05:00"),  # exact duplicate
        metrics_line("2024-01-01 00:10:00", sym="ETHUSDT"),  # another symbol: bad
        metrics_line("2024-01-01T00:15:00"),  # another time format: bad
        metrics_line("2024-01-01 00:20:00", oi="0E-8", value="0E-8", a="", b="", c="", d="-1"),  # nothing valid
        metrics_line("2024-01-02 00:00:00", oi="200"),  # next day in this file: kept and counted
        "2024-01-01 00:25:00,BTCUSDT,1",  # short line
    ])
    m = fu.load_metrics([day], "BTCUSDT")
    assert [t.isoformat() for t in m["ts"]] == [
        "2024-01-01T00:00:00+00:00", "2024-01-01T00:05:00+00:00", "2024-01-02T00:00:00+00:00"]
    assert list(m.columns) == ["ts", *fu.METRIC_FIELDS.values()]
    first = m.iloc[0]
    assert first["open_interest"] == 100.5 and first["open_interest_value"] == 2000.0
    assert np.isnan(first["top_account_ls_ratio"]) and np.isnan(first["top_position_ls_ratio"])
    assert np.isnan(first["account_ls_ratio"]) and np.isnan(first["taker_buy_sell_ratio"])
    assert m.iloc[1][list(fu.METRIC_FIELDS.values())].tolist() == [100.5, 2000.0, 1.1, 1.2, 1.3, 0.9]
    a = m.attrs
    assert (a["rows_read"], a["dropped_bad"], a["exact_duplicates"], a["conflicting_duplicates"]) == (8, 4, 1, 0)
    assert a["files_out_of_order"] == 1 and a["rows_outside_file_period"] == 1
    assert a["missing_top_account_ls_ratio"] == 1 and a["missing_top_position_ls_ratio"] == 1
    assert a["invalid_account_ls_ratio"] == 1 and a["invalid_taker_buy_sell_ratio"] == 1
    assert a["missing_open_interest"] == a["invalid_open_interest"] == 0  # the all-invalid row is dropped, not counted


def test_load_klines_5m(tmp_path):
    t0 = ms("2024-01-01 00:00")
    rows = [
        f"{t0},100,101,99,100.5,10,{t0 + 299_999},1000,5,4,400,0",
        f"{t0 + 300_000},100.5,101,99,100,10,0,0,5,11,0,0",  # taker volume over the volume: bad
        f"{t0 + 600_000},0,101,99,100,10,0,0,5,1,0,0",  # zero price: bad
    ]
    old = zip_csv(tmp_path / "BTCUSDT-5m-2024-01.zip", rows)  # older files have no header
    k = fu.load_klines_5m([old])
    assert k[["open", "close", "volume", "taker_buy_volume"]].values.tolist() == [[100.0, 100.5, 10.0, 4.0]]
    assert k["ts"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC") and k.attrs["dropped_bad"] == 2
    new = zip_csv(tmp_path / "BTCUSDT-5m-2024-02.zip", [",".join(fu.KLINE_HEADER), rows[0].replace(str(t0), str(t0 * 1000), 1)])
    assert fu.load_klines_5m([new])["ts"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")  # us stamps detected


# ============================================================================ cleaning


def frame(ts: list[str], **cols) -> pd.DataFrame:
    out = pd.DataFrame({"ts": pd.DatetimeIndex(pd.to_datetime(ts, utc=True, format="mixed")).as_unit("us")})
    for name in fu.METRIC_FIELDS.values():
        out[name] = np.asarray(cols.get(name, np.arange(1.0, len(ts) + 1)), dtype=float)
    return out


def grid(n: int, start="2024-01-01") -> list[str]:
    return [str(t) for t in pd.date_range(start, periods=n, freq="5min", tz="UTC")]


def test_mark_stale_is_causal_and_exact():
    oi = [5.0] * 14 + [6.0, 7.0]  # unchanged for 13 rows = 65 minutes, then moves
    acc = [1.0, 2.0] + [3.0] * 12 + [np.nan, 3.0]  # a NaN ends a run
    f = frame(grid(16), open_interest=oi, account_ls_ratio=acc)
    out, rep = fu.mark_stale(f)
    # the run starts at row 0; rows whose value is at least 1 hour old (rows 12, 13: 60 and 65 min) become NaN
    assert np.isnan(out["open_interest"].to_numpy()[12:14]).all()
    assert out["open_interest"].to_numpy()[:12].tolist() == [5.0] * 12 and out["open_interest"].iloc[14] == 6.0
    assert np.isnan(out["open_interest_value"].to_numpy()[12:14]).all()  # value without open interest
    assert out["account_ls_ratio"].iloc[13] == 3.0  # its run started at row 2: 55 minutes, kept
    assert rep["stale_rows"]["open_interest"] == 2 and rep["stale_rows"]["account_ls_ratio"] == 0
    assert rep["stale_runs"] == [{"field": "open_interest", "from": "2024-01-01T01:00:00+00:00",
                                  "to": "2024-01-01T01:05:00+00:00", "rows": 2}]
    assert rep["value_without_open_interest"] == 2 and rep["after"] == "1 h"
    assert f["open_interest"].iloc[12] == 5.0  # the input is not modified


def test_mark_stale_never_looks_ahead():
    """Changing rows after a cut never changes the cleaned rows before it (the rule is causal)."""
    base = [5.0] * 30
    f = frame(grid(30), open_interest=base)
    cleaned, _ = fu.mark_stale(f)
    for cut in (5, 12, 13, 20):
        tampered = f.copy()
        tampered.loc[cut:, "open_interest"] = np.arange(30 - cut) + 100.0
        got, _ = fu.mark_stale(tampered)
        pd.testing.assert_frame_equal(got.iloc[:cut], cleaned.iloc[:cut])


def test_mark_stale_counts_gaps_by_time_not_rows():
    ts = ["2024-01-01 00:00", "2024-01-01 00:05", "2024-01-01 01:30"]  # same value over a 90-minute gap
    out, rep = fu.mark_stale(frame(ts, open_interest=[5.0, 5.0, 5.0]))
    assert out["open_interest"].isna().tolist() == [False, False, True] and rep["stale_rows"]["open_interest"] == 1


def test_with_known_at_drops_what_is_known_at_or_after_the_cut():
    f = frame(["2024-06-30 23:50", "2024-06-30 23:55"])
    f.attrs = {"files": 1}
    cut = pd.Timestamp("2024-07-01", tz="UTC")
    out, dropped = fu.with_known_at(f, fu.METRICS_LAG, cut)
    assert dropped == 1 and len(out) == 1 and list(out.columns[:2]) == ["ts", "known_at"]
    assert out["known_at"].iloc[0] == pd.Timestamp("2024-06-30 23:55", tz="UTC") and out.attrs == {"files": 1}
    assert str(out["known_at"].dtype) == "datetime64[us, UTC]"


def test_runs_helpers():
    assert fu._runs(np.array([False, True, True, False, True])) == [(1, 2), (4, 4)]
    assert fu._longest_run(np.array([True, False, True])) == (0, 0)  # ties: the earliest
    assert fu._longest_run(np.array([False, False])) is None


# ============================================================================ checks


def funding_table(ts: list[str], rate: list[float], hours=8.0) -> pd.DataFrame:
    return pd.DataFrame({"ts": pd.DatetimeIndex(pd.to_datetime(ts, utc=True, format="mixed")).as_unit("us"),
                         "rate": np.asarray(rate, dtype=float), "interval_hours": float(hours)})


def test_check_funding_known_answer():
    ts = ["2024-01-01 00:00:00.002", "2024-01-01 08:00", "2024-01-02 00:00", "2024-01-02 07:59:59.990",
          "2024-01-02 16:02"]
    c = fu.check_funding(funding_table(ts, [0.0001, -0.003, 0.0002, 0.0001, 0.001]))
    assert c["rows"] == 5 and c["first"] == "2024-01-01T00:00:00.002000+00:00" and c["interval_hours"] == {"8": 5}
    assert c["grid_offset_ms"] == {"min": -10, "max": 120_000} and c["off_grid_over_1min"] == 1
    assert c["gaps"] == 1 and c["missing"] == 1  # 2024-01-01 16:00 is missing
    assert c["longest_gaps"] == [{"after": "2024-01-01T08:00:00+00:00", "before": "2024-01-02T00:00:00+00:00",
                                  "missing": 1}]
    assert c["rate"]["min"] == -0.003 and c["rate"]["max"] == 0.001 and c["rate"]["median"] == 0.0001
    assert [x["rate"] for x in c["largest_abs"]] == [-0.003, 0.001, 0.0002, 0.0001, 0.0001]


def test_check_metrics_known_answer():
    ts = grid(3, "2024-01-01 23:45") + ["2024-01-02 00:10", "2024-01-02 00:15:30"]
    f = frame(ts, open_interest=[100, 100, 200, 200, 210], top_account_ls_ratio=[np.nan] * 5)
    c = fu.check_metrics(f)
    assert (c["rows"], c["expected_rows"], c["off_grid"], c["gaps"], c["missing"]) == (5, 7, 1, 1, 2)
    assert c["longest_gaps"] == [{"after": "2024-01-01T23:55:00+00:00", "before": "2024-01-02T00:10:00+00:00",
                                  "missing": 2}]  # 00:00 and 00:05; the off-grid 5.5-minute step is no gap
    assert c["days"] == 2 and c["days_short"] == 2 and c["days_empty"] == 0
    assert c["short_days"] == [{"day": "2024-01-01", "rows": 3}, {"day": "2024-01-02", "rows": 2}]
    assert c["fields"]["top_account_ls_ratio"] == {"rows": 0, "first": None, "last": None, "longest_absence": {
        "from": "2024-01-01T23:45:00+00:00", "to": "2024-01-02T00:15:30+00:00", "rows": 5}}
    assert c["fields"]["open_interest"]["longest_absence"] is None
    assert c["open_interest_largest_moves"][0] == {"ts": "2024-01-01T23:55:00+00:00",
                                                   "abs_log_change": round(np.log(2), 6)}
    assert len(c["open_interest_largest_moves"]) == 4  # the first row has no move
    assert c["open_interest_longest_unchanged"] == {"from": "2024-01-01T23:45:00+00:00",
                                                    "to": "2024-01-01T23:50:00+00:00", "rows": 2}
    c2 = fu.check_metrics(frame(grid(2), open_interest=[1.0, 2.0]))
    assert c2["open_interest_longest_unchanged"] is None and c2["days_short"] == 1 and c2["gaps"] == 0


def test_gaps_needs_two_rows():
    assert fu._gaps(pd.DatetimeIndex(["2024-01-01"], tz="UTC"), np.array([1])) == []


# ============================================================================ timing


def klines(start: str, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    volume = rng.uniform(10, 20, n)
    return pd.DataFrame({
        "ts": pd.date_range(start, periods=n, freq="5min", tz="UTC").as_unit("us"),
        "open": np.concatenate([[100.0], close[:-1]]), "close": close, "volume": volume,
        "taker_buy_volume": volume * rng.uniform(0.2, 0.8, n),
    })


def metrics_from(kl: pd.DataFrame, day: str, taker_offset: int, price_offset: int, oi=1000.0) -> pd.DataFrame:
    """288 rows of one day whose taker ratio is the kline period starting at T + taker_offset and whose value /
    open interest is the price at T + price_offset (the open of the kline starting then)."""
    k = kl.set_index("ts")
    ratio = k["taker_buy_volume"] / (k["volume"] - k["taker_buy_volume"])
    ts = pd.date_range(day, periods=288, freq="5min", tz="UTC").as_unit("us")
    out = frame([str(t) for t in ts])
    out["taker_buy_sell_ratio"] = ratio.reindex(ts + pd.Timedelta(minutes=taker_offset)).to_numpy()
    out["open_interest"] = oi
    out["open_interest_value"] = oi * k["open"].reindex(ts + pd.Timedelta(minutes=price_offset)).to_numpy()
    return out


def test_metrics_timing_finds_each_days_convention():
    kl = klines("2024-04-24 23:00", 4 * 288, seed=3)
    days = [metrics_from(kl, "2024-04-25", -5, 0), metrics_from(kl, "2024-04-26", 0, 5),
            metrics_from(kl, "2024-04-27", 0, 5)]
    t = fu.metrics_timing(pd.concat(days, ignore_index=True), kl)
    assert [d["day"] for d in t["days"]] == ["2024-04-25", "2024-04-26", "2024-04-27"]
    first = t["days"][0]
    assert first["taker"] == {"offset": -5, "median_error": first["taker"]["median_error"], "conclusive": True}
    assert first["taker"]["median_error"] < 1e-12 and first["price"]["offset"] == 0 and first["reach_minutes"] == 0
    assert t["days"][1]["reach_minutes"] == 5 and t["days"][1]["price"]["offset"] == 5
    assert t["runs"] == [
        {"from": "2024-04-25", "to": "2024-04-25", "days": 1, "taker_offset": -5, "price_offset": 0},
        {"from": "2024-04-26", "to": "2024-04-27", "days": 2, "taker_offset": 0, "price_offset": 5},
    ]
    assert t["max_reach_minutes"] == 5 and t["inconclusive_days"] == 0


def test_metrics_timing_flags_data_that_reach_further_and_inconclusive_days():
    kl = klines("2024-04-24 23:00", 3 * 288, seed=4)
    late = metrics_from(kl, "2024-04-25", 5, 10)  # data up to T + 10 minutes: more than the 5-minute lag
    no_taker = metrics_from(kl, "2024-04-26", 0, 5)
    no_taker["taker_buy_sell_ratio"] = np.nan  # a field missing all day: that check can't decide
    t = fu.metrics_timing(pd.concat([late, no_taker], ignore_index=True), kl)
    assert t["days"][0]["reach_minutes"] == 10 and t["max_reach_minutes"] == 10
    assert t["days"][1]["taker"] == {"offset": None, "median_error": None, "conclusive": False}
    assert t["days"][1]["reach_minutes"] == 5
    few = metrics_from(kl, "2024-04-25", 0, 5).iloc[: fu.MIN_MATCHED - 1]  # too few rows for a verdict
    t2 = fu.metrics_timing(few, kl)
    assert t2["max_reach_minutes"] is None and t2["inconclusive_days"] == 1
    assert t2["runs"] == [{"from": "2024-04-25", "to": "2024-04-25", "days": 1, "taker_offset": None,
                           "price_offset": None}]


def test_best_needs_a_clear_winner():
    rows = fu.MIN_MATCHED
    assert fu._best({0: np.full(rows, 0.1), 5: np.full(rows, 0.15)}) == (0, 0.1, False)
    assert fu._best({0: np.full(rows, 0.1), 5: np.full(rows, 0.3)}) == (0, 0.1, True)
    assert fu._best({0: np.zeros(rows), -5: np.zeros(rows)}) == (0, 0.0, False)  # a tie goes to the smaller shift
    assert fu._best({0: np.zeros(rows), 5: np.zeros(rows - 1)}) == (None, None, False)
