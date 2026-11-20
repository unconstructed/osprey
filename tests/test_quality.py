"""lab/data/quality.py: data quality checks on hand-built bars with known answers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lab.data import quality

H = pd.Timedelta(hours=1)
D = pd.Timedelta(days=1)


def bars_at(index, close=None, spread=0.01, volume=1.0) -> pd.DataFrame:
    """Valid bars on ``index`` (open = previous close), closes default to 100 rising slowly."""
    index = pd.DatetimeIndex(index, name="ts")
    close = np.asarray(close if close is not None else 100 + 0.1 * np.arange(len(index)), dtype=float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * (1 + spread),
            "low": np.minimum(open_, close) * (1 - spread),
            "close": close,
            "volume": np.full(len(index), float(volume)),
        },
        index=index,
    )


def grid(start, n, step=D):
    return pd.date_range(start, periods=n, freq=step, tz="UTC")


# ----------------------------------------------------------------------------------------------- gaps


def test_find_gaps_known_answer():
    idx = grid("2020-01-02", 10).delete([3, 4, 7])  # missing 01-05, 01-06 and 01-09
    gaps = quality.find_gaps(idx, D)
    assert gaps == [
        {"after": "2020-01-04T00:00:00+00:00", "before": "2020-01-07T00:00:00+00:00", "missing": 2},
        {"after": "2020-01-08T00:00:00+00:00", "before": "2020-01-10T00:00:00+00:00", "missing": 1},
    ]
    assert quality.find_gaps(idx[:1], D) == []


@given(st.lists(st.booleans(), min_size=2, max_size=200), st.sampled_from(["1d", "1h"]))
def test_find_gaps_matches_brute_force(keep, interval):
    step = quality.step_of(interval)
    full = grid("2021-03-01", len(keep), step)
    idx = full[np.array(keep)]
    gaps = quality.find_gaps(idx, step)
    if len(idx) < 2:
        assert gaps == []
        return
    inside = full[(full >= idx[0]) & (full <= idx[-1])]
    assert sum(g["missing"] for g in gaps) == len(inside) - len(idx)
    for g in gaps:  # each gap's missing bars are exactly the grid points strictly between its ends
        between = inside[(inside > pd.Timestamp(g["after"])) & (inside < pd.Timestamp(g["before"]))]
        assert len(between) == g["missing"] and not idx.isin(between).any()


def test_step_of_rejects_other_intervals():
    with pytest.raises(ValueError, match="interval must be one of"):
        quality.step_of("4h")


# ----------------------------------------------------------------------------------------------- check_series


def test_check_series_counts_gaps_and_span():
    idx = grid("2020-01-02", 30).delete([5, 6, 7, 20])
    out = quality.check_series(bars_at(idx), "1d")
    assert out["rows"] == 26 and out["expected_bars"] == 30
    assert out["gaps"] == 2 and out["missing_bars"] == 4
    assert out["longest_gaps"][0] == {
        "after": "2020-01-06T00:00:00+00:00", "before": "2020-01-10T00:00:00+00:00", "missing": 3,
    }
    assert out["start"] == "2020-01-02T00:00:00+00:00" and out["end"] == "2020-01-31T00:00:00+00:00"
    assert out["off_grid"] == 0 and out["duplicates"] == 0 and not out["unsorted"]


def test_check_series_flags_off_grid_duplicate_and_unsorted_bars():
    idx = list(grid("2020-01-01 01:00", 5, H))
    idx[2] = idx[2] + pd.Timedelta(minutes=28)
    idx.append(idx[0])  # duplicate, out of order
    out = quality.check_series(bars_at(idx), "1h")
    assert out["off_grid"] == 1 and out["duplicates"] == 1 and out["unsorted"]


def test_check_series_counts_bad_ticks_and_zero_volume():
    b = bars_at(grid("2020-01-02", 6))
    b.iloc[1, b.columns.get_loc("low")] = -1.0  # non-positive
    b.iloc[2, b.columns.get_loc("high")] = b.iloc[2]["low"] * 0.5  # high below low and the body
    b.iloc[3, b.columns.get_loc("volume")] = 0.0
    out = quality.check_series(b, "1d")
    assert out["non_positive"] == 1 and out["ohlc_inconsistent"] == 1
    assert out["zero_volume"] == 1 and out["zero_volume_bars"] == ["2020-01-05T00:00:00+00:00"]


def test_extreme_move_uses_only_past_sigma():
    rng = np.random.default_rng(3)
    n = 120
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    close[90:] *= 1.5  # a +40.5% log jump at bar 90, about 40 sigma
    out = quality.check_series(bars_at(grid("2020-01-02", n), close, spread=0.001), "1d")
    assert out["extreme_moves"] == 1
    top = out["extreme_moves_top"][0]
    assert top["ts"] == grid("2020-01-02", n)[90].isoformat()
    assert top["log"] == pytest.approx(np.log(close[90] / close[89]), abs=1e-6)
    # the sigma is the std of the 30 log returns BEFORE the jump
    past = np.diff(np.log(close[59:90]))
    assert top["sigma"] == pytest.approx(np.std(past, ddof=1), abs=1e-6)
    assert top["k"] > 10


def test_extreme_wick_is_flagged_and_not_a_move():
    rng = np.random.default_rng(4)
    n = 80
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    b = bars_at(grid("2020-01-02", n), close, spread=0.001)
    b.iloc[60, b.columns.get_loc("low")] = 1.0  # flash crash print, close unaffected
    out = quality.check_series(b, "1d")
    assert out["extreme_moves"] == 0
    assert out["extreme_wicks"] == 1 and out["extreme_wicks_top"][0]["ts"] == b.index[60].isoformat()


def test_no_sigma_yet_means_nothing_flagged():
    close = [100.0, 200.0, 100.0, 300.0]
    out = quality.check_series(bars_at(grid("2020-01-02", 4), close), "1d")
    assert out["extreme_moves"] == 0 and out["extreme_moves_top"] == []


def test_stale_runs_and_the_longest():
    close = [1, 2, 2, 2, 3, 4, 4, 4, 4, 4, 5, 6, 6, 7]  # runs of 2 and 4 unchanged closes after the first
    out = quality.check_series(bars_at(grid("2020-01-02", len(close)), close), "1d", stale_bars=2)
    assert out["stale_runs"] == 2
    idx = grid("2020-01-02", len(close))
    assert out["longest_stale"] == {"from": idx[5].isoformat(), "to": idx[9].isoformat(), "unchanged_bars": 4}
    out3 = quality.check_series(bars_at(idx, close), "1d", stale_bars=5)
    assert out3["stale_runs"] == 0 and out3["longest_stale"] is None


def test_check_series_rejects_empty_bars():
    with pytest.raises(ValueError, match="no bars"):
        quality.check_series(bars_at(grid("2020-01-02", 3)).iloc[:0], "1d")


# ----------------------------------------------------------------------------------------------- daily vs hourly


def hourly_and_daily(days=5):
    rng = np.random.default_rng(1)
    hourly = bars_at(grid("2020-01-01 01:00", 24 * days, H), 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 24 * days))))
    hourly["volume"] = rng.uniform(1, 2, len(hourly))
    from lab.data.loaders import resample

    return resample(hourly, "1D"), hourly


def test_daily_equals_aggregated_hourly():
    daily, hourly = hourly_and_daily()
    out = quality.compare_intervals(daily, hourly)
    assert out["days_compared"] == 5 and out["daily_without_hourly"] == 0
    assert out["mismatches"] == {"open": 0, "high": 0, "low": 0, "close": 0}
    assert out["mismatched_days"] == [] and out["volume_max_rel_diff"] < 1e-12


def test_daily_vs_hourly_mismatch_is_listed():
    daily, hourly = hourly_and_daily()
    daily = daily.copy()
    daily.iloc[2, daily.columns.get_loc("close")] *= 1.01
    daily.iloc[2, daily.columns.get_loc("high")] *= 1.01
    daily.iloc[3, daily.columns.get_loc("volume")] = 0.0  # absolute volume difference where daily is 0
    extra = bars_at(pd.DatetimeIndex([daily.index[-1] + D]), [daily["close"].iloc[-1]])
    out = quality.compare_intervals(pd.concat([daily, extra]), hourly)
    assert out["mismatches"] == {"open": 0, "high": 1, "low": 0, "close": 1}
    assert out["daily_without_hourly"] == 1
    (m,) = out["mismatched_days"]
    assert m["ts"] == daily.index[2].isoformat() and m["daily"][3] == daily["close"].iloc[2]
    assert out["volume_max_rel_diff"] == pytest.approx(hourly["volume"].iloc[72:96].sum())


def test_daily_vs_hourly_with_no_common_day():
    daily, hourly = hourly_and_daily()
    later = daily.copy()
    later.index = later.index + 30 * D
    out = quality.compare_intervals(later, hourly)
    assert out["days_compared"] == 0 and out["volume_max_rel_diff"] == 0.0


# ----------------------------------------------------------------------------------------------- cross-check


def closes(values, start="2021-01-02"):
    return pd.Series(np.asarray(values, dtype=float), index=grid(start, len(values)))


def test_cross_check_lists_every_outlier_with_values():
    a = closes([100, 100, 100, 100])
    b = closes([100, 102, 100, 99.5])
    c = closes([100, 100, 97, 100])
    out = quality.cross_check({"kraken": a, "binance": b, "coinbase": c}, tolerance=0.01)
    assert out["sources"] == ["binance", "coinbase", "kraken"]
    by_pair = {p["pair"]: p for p in out["pairs"]}
    assert by_pair["binance/kraken"]["outliers"] == 1 and by_pair["binance/coinbase"]["outliers"] == 2
    assert by_pair["coinbase/kraken"]["outliers"] == 1
    assert by_pair["binance/kraken"]["max_abs"] == pytest.approx(0.02)
    assert by_pair["binance/kraken"]["max_day"] == "2021-01-02"  # close 2021-01-03 00:00 = trading day 01-02
    assert [o["day"] for o in out["outliers"]] == ["2021-01-02", "2021-01-03"]
    first, second = out["outliers"]
    assert first["values"] == {"binance": 102.0, "coinbase": 100.0, "kraken": 100.0}
    assert first["pairs"] == {"binance/coinbase": 0.02, "binance/kraken": 0.02}
    assert second["pairs"] == {"binance/coinbase": pytest.approx(0.030928, abs=1e-6), "coinbase/kraken": -0.03}
    assert "hourly_bars" not in first


def test_cross_check_median_by_trading_year_and_missing_values():
    a = closes([100, 100, 100], start="2020-12-31")  # closes 12-31, 01-01, 01-02 -> trading days 2020, 2020, 2021
    b = closes([101, 101, 99], start="2020-12-31")
    b.iloc[0] = np.nan
    out = quality.cross_check({"a": a, "b": b}, tolerance=0.5)
    (pair,) = out["pairs"]
    assert pair["pair"] == "a/b" and pair["days"] == 2 and pair["outliers"] == 0
    assert pair["median_by_year"] == {2020: pytest.approx(100 / 101 - 1), 2021: pytest.approx(100 / 99 - 1)}
    assert out["outliers"] == []


def test_cross_check_hourly_bars_explain_a_stale_close():
    a = closes([100, 100])
    b = closes([100, 105])
    hours = grid("2021-01-02 01:00", 48, H).delete(range(10, 20))  # 10 hours missing on trading day 01-02
    out = quality.cross_check({"a": a, "b": b}, 0.01, hourly={"b": hours, "a": grid("2021-01-02 01:00", 48, H)})
    (o,) = out["outliers"]
    assert o["day"] == "2021-01-02" and o["hourly_bars"] == {"a": 24, "b": 14}


def test_cross_check_pair_without_common_days():
    out = quality.cross_check({"a": closes([1, 2]), "b": closes([1, 2], start="2022-01-01")}, 0.01)
    (pair,) = out["pairs"]
    assert pair["days"] == 0 and pair["median"] is None and pair["max_day"] is None and pair["median_by_year"] == {}


def test_cross_check_arguments():
    with pytest.raises(ValueError, match="tolerance"):
        quality.cross_check({"a": closes([1]), "b": closes([1])}, 0.0)
    with pytest.raises(ValueError, match="two sources"):
        quality.cross_check({"a": closes([1])}, 0.01)


# ----------------------------------------------------------------------------------------------- alignment


def walk(n, seed, step, start="2021-01-01 01:00"):
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=grid(start, n, step))


@pytest.mark.parametrize("step", [H, D])
def test_aligned_sources(step):
    a = walk(500, 1, step)
    b = a * (1 + np.random.default_rng(2).normal(0, 1e-4, len(a)))
    out = quality.lag_alignment(a, b, step)
    assert out["best_lag"] == 0 and out["aligned"]
    assert set(out["median_abs_log_diff"]) == {str(k) for k in range(-3, 4)}
    assert out["median_abs_log_diff"]["0"] < out["median_abs_log_diff"]["1"] / 10


@pytest.mark.parametrize("shift", [-2, 1])
def test_a_shifted_source_is_caught(shift):
    a = walk(500, 5, H)
    b = pd.Series(a.to_numpy(), index=a.index + shift * H)  # b labels every price `shift` hours later
    out = quality.lag_alignment(a, b, H)
    assert out["best_lag"] == shift and not out["aligned"]


def test_alignment_without_overlap():
    a = walk(10, 1, D)
    out = quality.lag_alignment(a, walk(10, 1, D, start="2030-01-01"), D)
    assert out["best_lag"] is None and not out["aligned"]
    assert all(v is None for v in out["median_abs_log_diff"].values())


# ----------------------------------------------------------------------------------------------- window coverage

TRAIN = (pd.Timestamp("2017-01-01", tz="UTC"), pd.Timestamp("2017-01-10", tz="UTC"))


def test_window_fully_covered():
    idx = grid("2016-12-20", 40)
    out = quality.window_coverage(idx, "1d", TRAIN)
    assert out["expected"] == 10 and out["present"] == 10 and out["covered"] and out["complete"]
    assert out["first"] == "2017-01-02T00:00:00+00:00" and out["last"] == "2017-01-11T00:00:00+00:00"
    assert out["window"] == ["2017-01-01T00:00:00+00:00", "2017-01-11T00:00:00+00:00"]


def test_window_late_start_early_end_and_holes():
    idx = grid("2017-01-04", 5).delete(2)  # closes 01-04, 01-05, 01-07, 01-08
    out = quality.window_coverage(idx, "1d", TRAIN)
    assert out["late_start_bars"] == 2 and out["early_end_bars"] == 3 and out["missing_inside"] == 1
    assert out["gaps"] == [{"after": "2017-01-05T00:00:00+00:00", "before": "2017-01-07T00:00:00+00:00", "missing": 1}]
    assert out["present"] == 4 and not out["covered"] and not out["complete"]


def test_window_hourly_and_open_ended():
    idx = grid("2017-01-01 01:00", 30, H)
    out = quality.window_coverage(idx, "1h", (TRAIN[0], None))
    assert out["expected"] == 30 and out["present"] == 30 and out["complete"]
    assert out["window"][1] == idx[-1].isoformat()


def test_window_with_no_bars_inside():
    out = quality.window_coverage(grid("2018-01-01", 5), "1d", TRAIN)
    assert out["present"] == 0 and out["first"] is None and out["late_start_bars"] == 10 and not out["covered"]
    before = quality.window_coverage(grid("2016-01-01", 5), "1d", (TRAIN[0], None))
    assert before["expected"] == 0 and before["present"] == 0
