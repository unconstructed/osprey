"""lab/config.py: YAML loading, the fixed split windows and the close-time selection rule (merge: comparer
finding, the documented rule 'start <= ts < end + 1 day' was off by one bar under close-time labels)."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.config import CONFIG_DIR, in_window, load_yaml, splits


def utc(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def test_splits_reads_the_fixed_windows_as_utc_and_latest_as_open_ended():
    w = splits()
    assert w == {
        "train": (utc("2017-01-01"), utc("2022-12-31")),
        "validate": (utc("2023-01-01"), utc("2024-06-30")),
        "test": (utc("2024-07-01"), None),
    }
    assert load_yaml("splits") == load_yaml("splits", CONFIG_DIR)


def test_load_yaml_from_another_directory_and_empty_file(tmp_path):
    (tmp_path / "splits.yaml").write_text("a: {start: 2020-01-01, end: LATEST}\n")
    assert splits(tmp_path) == {"a": (utc("2020-01-01"), None)}
    (tmp_path / "empty.yaml").write_text("")
    assert load_yaml("empty", tmp_path) == {}


def test_daily_close_time_bars_fall_in_the_right_window():
    w = splits()
    idx = pd.date_range("2022-12-30", "2023-01-03", freq="D", tz="UTC", name="ts")  # close times
    # the bar labelled 2023-01-01 00:00 is trading day 2022-12-31: the last train day, not validate
    assert in_window(idx, w["train"]).tolist() == [True, True, True, False, False]
    assert in_window(idx, w["validate"]).tolist() == [False, False, False, True, True]
    edge = pd.date_range("2024-06-30", "2024-07-02", freq="D", tz="UTC")
    assert in_window(edge, w["validate"]).tolist() == [True, True, False]  # 07-01 00:00 closes day 06-30
    assert in_window(edge, w["test"]).tolist() == [False, False, True]


@pytest.mark.parametrize("name", ["train", "validate", "test"])
def test_hourly_bars_partition_without_gaps_or_overlap(name):
    w = splits()
    idx = pd.date_range("2016-12-31 01:00", "2025-01-01", freq="h", tz="UTC")
    masks = {k: in_window(idx, v) for k, v in w.items()}
    assert (sum(m.astype(int) for m in masks.values())[idx > utc("2017-01-01")] == 1).all()
    first = idx[masks[name]][0]
    assert first == w[name][0] + pd.Timedelta(hours=1)  # the first hour of the window's first day
