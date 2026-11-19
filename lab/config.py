"""Read the repo's YAML config files (config/*.yaml).

The files in config/ belong to the owner (splits, costs) and the risk-officer (risk levels).
Code reads them; it never writes them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


def load_yaml(name: str, config_dir: Path | None = None) -> dict:
    """Load ``config/<name>.yaml`` and return it as a dict (an empty file gives ``{}``)."""
    path = (config_dir or CONFIG_DIR) / f"{name}.yaml"
    with path.open() as fh:
        data = yaml.safe_load(fh)
    return data or {}


def splits(config_dir: Path | None = None) -> dict[str, tuple[pd.Timestamp, pd.Timestamp | None]]:
    """The fixed train / validate / test windows as UTC timestamps (inclusive dates).

    ``end: latest`` becomes ``None`` (open-ended). Each end is the last *day* of the window. Bars are
    indexed by their CLOSE time (the daily bar of day D is labelled D+1 00:00), so a window holds the bars
    with ``start < ts <= end + 1 day``: use :func:`in_window`.
    """
    raw = load_yaml("splits", config_dir)
    out: dict[str, tuple[pd.Timestamp, pd.Timestamp | None]] = {}
    for name, window in raw.items():
        start = pd.Timestamp(window["start"], tz="UTC")
        end_raw = window["end"]
        end = None if str(end_raw).lower() == "latest" else pd.Timestamp(end_raw, tz="UTC")
        out[name] = (start, end)
    return out


def in_window(index: pd.DatetimeIndex, window: tuple[pd.Timestamp, pd.Timestamp | None]) -> np.ndarray:
    """Boolean mask of the bars in ``window`` (a value of :func:`splits`), for an index of bar CLOSE times.

    A bar belongs to the window when it closes after the window's first midnight and no later than the
    midnight that ends its last day: ``start < ts <= end + 1 day`` (no upper bound when ``end`` is None).
    This works for any bar length that divides a day (daily, hourly).
    """
    start, end = window
    mask = index > start
    if end is not None:
        mask &= index <= end + pd.Timedelta(days=1)
    return np.asarray(mask, dtype=bool)
