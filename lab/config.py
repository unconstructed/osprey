"""Read the repo's YAML config files (config/*.yaml).

The files in config/ belong to the owner (splits, costs) and the risk-officer (risk levels).
Code reads them; it never writes them.
"""

from __future__ import annotations

from pathlib import Path

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

    ``end: latest`` becomes ``None`` (open-ended). Each end is the last *day* of the window, so
    callers select bars with ``start <= ts < end + 1 day``.
    """
    raw = load_yaml("splits", config_dir)
    out: dict[str, tuple[pd.Timestamp, pd.Timestamp | None]] = {}
    for name, window in raw.items():
        start = pd.Timestamp(window["start"], tz="UTC")
        end_raw = window["end"]
        end = None if str(end_raw).lower() == "latest" else pd.Timestamp(end_raw, tz="UTC")
        out[name] = (start, end)
    return out
