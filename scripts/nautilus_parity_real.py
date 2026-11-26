"""Milestone 2 check on real data: the Nautilus runner against the reference runner on catalog bars.

Train window only (closes up to 2023-01-01, AGENTS.md "Splits"; nothing from validate or test is read). For each
rule, at the config costs and at 2x, it prints the trade count, both Sharpes, the largest per-bar difference of
every result column, and the time per run. A benchmark check, not a strategy result: the parameters are fixed
here, nothing is searched, and no number decides anything.

    uv run python scripts/nautilus_parity_real.py [--interval 1d]
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from lab.data.catalog import load_bars, snapshot_id
from lab.runner import nautilus, reference
from lab.runner.reference import Costs

LAST_TRAIN_CLOSE = "2023-01-01"
CASES = (
    ("buy and hold BTC", reference.buy_and_hold, {}),
    ("50/50 BTC/USDC, monthly rebalance", reference.constant_mix, {"weight": 0.5, "every": 30}),
    (
        "dip buy: 10% drop over 20 bars, 10% stop, 30-bar hold",
        reference.dip_buy,
        {"drop": 0.1, "lookback": 20, "stop": 0.1, "hold": 30},
    ),
    (
        "dip buy: 5% drop over 5 bars, vol target 60%",
        reference.dip_buy,
        {"drop": 0.05, "lookback": 5, "vol_target": 0.6},
    ),
)
COLS = ["ret", "position", "turnover", "cost"]


def sharpe(ret: np.ndarray, per_year: float) -> float:
    return float(ret.mean() / ret.std(ddof=1) * np.sqrt(per_year))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interval", default="1d", choices=["1d", "1h"])
    args = parser.parse_args()
    bars = load_bars("BTC/USD.KRAKEN", args.interval, start="2017-01-01", end=LAST_TRAIN_CLOSE)
    if bars.index[-1] > pd.Timestamp(LAST_TRAIN_CLOSE, tz="UTC"):
        raise SystemExit("read past the train window")
    per_year = 365 if args.interval == "1d" else 365 * 24
    print(
        f"snapshot {snapshot_id()}, BTC/USD Kraken {args.interval}, {len(bars)} bars "
        f"{bars.index[0]:%Y-%m-%d} .. {bars.index[-1]:%Y-%m-%d}"
    )
    print(
        f"{'rule':56} {'costs':5} {'fills NT':>8} {'Sharpe ref':>10} {'Sharpe NT':>10} {'max |diff|':>11} {'NT s/run':>8}"
    )
    for label, rule, params in CASES:
        for k, costs in (("1x", Costs.from_yaml()), ("2x", Costs.from_yaml().stressed())):
            ref = rule(params, bars, costs)
            start = time.perf_counter()
            nt = nautilus.run(rule, params, bars, costs)
            seconds = time.perf_counter() - start
            rf, nf = ref["turnover"].to_numpy() > 0, nt["turnover"].to_numpy() > 0
            # The one documented difference (TESTING.md #61): the reference trades a leg of at most MIN_LEG of the
            # book (round-off) and pays gas for it; Nautilus does not send it. Every other fill must match.
            skipped = rf & ~nf
            if (nf & ~rf).any() or (ref["turnover"].to_numpy()[skipped] > nautilus.MIN_LEG).any():
                raise SystemExit(f"{label} {k}: the runners filled on different bars")
            upto = int(np.argmax(skipped)) if skipped.any() else len(bars)
            diff = float(np.abs(nt[COLS].to_numpy()[:upto] - ref[COLS].to_numpy()[:upto]).max())
            if skipped.any():
                # After a skipped round-off leg the books differ by its gas share g. Every later cost is a share of a
                # book that is g larger on Nautilus: gas shares shrink by up to g of themselves and slippage moves by
                # less, so the final value ratio is 1 / (1 - g) to within g x the later costs' total share.
                ratio = np.prod(1 + nt["ret"].to_numpy()) / np.prod(1 + ref["ret"].to_numpy())
                g = ref["cost"].to_numpy()[skipped]
                expected = 1 / np.prod(1 - g)
                bound = g.sum() * nt["cost"].to_numpy()[upto:].sum() + nautilus.TOL
                if abs(ratio / expected - 1) > bound:
                    raise SystemExit(
                        f"{label} {k}: value ratio {ratio} vs skipped gas {expected}, bound {bound:.1e}"
                    )
                note = (
                    f"  ({int(skipped.sum())} round-off leg skipped from bar {upto}: value ratio off its gas by "
                    f"{abs(ratio / expected - 1):.1e}, bound {bound:.1e})"
                )
            else:
                note = ""
            s_ref, s_nt = sharpe(ref["ret"].to_numpy(), per_year), sharpe(nt["ret"].to_numpy(), per_year)
            print(
                f"{label:56} {k:5} {nt.attrs['n_trades']:>8} {s_ref:>10.4f} {s_nt:>10.4f} {diff:>11.1e} {seconds:>8.3f}{note}"
            )
            if diff > nautilus.TOL:
                raise SystemExit(f"{label} {k}: the runners differ by {diff:.3e} > {nautilus.TOL}")


if __name__ == "__main__":
    main()
