"""Power check for a2_tamper.py: plant a one-bar leak (T3's up-day signal and b_up_day read close[t+1]) and
confirm the same harness flags it. Train closes only."""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import runpy
import sys

import numpy as np

sys.path.insert(0, REPO + "/research/dip-timing")
from lab.models import dips  # noqa: E402

_orig = dips.up_day


def leaky_up_day(bars):
    close = bars["close"].to_numpy(dtype=float)
    high = bars["high"].to_numpy(dtype=float)
    out = np.zeros(len(close), dtype=bool)
    out[1:-1] = close[2:] > high[:-2]  # LEAK: tomorrow's close against yesterday's high
    return out


dips.up_day = leaky_up_day
runpy.run_path(sys.argv[1] if len(sys.argv) > 1 else str(_P(__file__).with_name("a2_tamper.py")), run_name="__main__")
