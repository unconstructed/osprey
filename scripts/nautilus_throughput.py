"""Throughput of the Nautilus runner (AGENTS.md "Running many simulations", rule 5).

Times full-history backtests on one core and prints backtests per hour per core, for the Nautilus runner and the
reference runner side by side. Synthetic bars of the real history's length (daily from 2017-01-01, and hourly
over the six train years), so it runs without the data catalog; the engine's cost depends on the number of
bars and fills, not on where the prices came from.

    uv run python scripts/nautilus_throughput.py [--repeats 5]
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from lab.data.synthetic import synthetic_market
from lab.runner import nautilus, reference

CASES = (
    (
        "dip_buy (drop 10%, 20 bars, stop 10%, hold 30)",
        reference.dip_buy,
        {"drop": 0.1, "lookback": 20, "stop": 0.1, "hold": 30},
    ),
    ("50/50 rebalance every 30 bars", reference.constant_mix, {"weight": 0.5, "every": 30}),
    ("50/50 rebalance every bar (worst case: a fill on every bar)", reference.constant_mix, {"weight": 0.5}),
)


def hourly(daily: pd.DataFrame, n_hours: int, seed: int) -> pd.DataFrame:
    """Hourly bars with the daily path's volatility scaled by 1/sqrt(24) (shape only matters for timing)."""
    rng = np.random.default_rng(seed)
    vol = np.log(daily["close"]).diff().std() / np.sqrt(24)
    body = rng.normal(0.0, vol, n_hours)
    close = 20_000.0 * np.exp(np.cumsum(body))
    open_ = close / np.exp(body)
    index = pd.date_range("2017-01-01 01:00", periods=n_hours, freq="h", tz="UTC", name="ts")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


def per_hour(fn, repeats: int) -> tuple[float, int]:
    fn()  # warm up (imports, first engine)
    start = time.perf_counter()
    for _ in range(repeats):
        result = fn()
    seconds = (time.perf_counter() - start) / repeats
    return 3600.0 / seconds, result.attrs["n_trades"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    daily = synthetic_market(3_420, assets=("BTC",), seed=21, start="2017-01-01")["BTC"]  # to 2026-05
    panels = {
        "daily, 3,420 bars (2017-2026)": daily,
        "hourly, 52,560 bars (6 train years)": hourly(daily, 52_560, 7),
    }
    print(f"{'bars':38} {'rule':58} {'fills':>6} {'Nautilus /h/core':>17} {'reference /h/core':>18}")
    for label, bars in panels.items():
        for name, rule, params in CASES:
            if label.startswith("hourly") and "every bar" in name:
                continue  # gas on 52,560 fills ruins a 10,000 USD book: both runners refuse it
            nt, fills = per_hour(lambda r=rule, p=params, b=bars: nautilus.run(r, p, b), args.repeats)
            ref, _ = per_hour(lambda r=rule, p=params, b=bars: r(p, b), args.repeats)
            print(f"{label:38} {name:58} {fills:>6} {nt:>17,.0f} {ref:>18,.0f}")


if __name__ == "__main__":
    main()
