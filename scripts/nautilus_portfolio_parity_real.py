"""Milestone 3 check on real data: the multi-asset Nautilus runner against ``lab/runner/portfolio.py`` on catalog bars.

Train window only (closes up to 2023-01-01, AGENTS.md "Splits"; nothing from validate or test is read). Kraken and
Binance, BTC + ETH panels (``lab.data.panel.load_panel``), daily or hourly, at the config costs and at 2x. For each
fixed setting it prints the fill count, both Sharpes, the largest per-bar difference of every result column, and the
time per run on each engine (runs per hour per core). A benchmark check, not a strategy result: the settings are
fixed here, nothing is searched, and no number decides anything.

Every disagreement is reported. The documented differences (TESTING.md #65) are checked, not ignored: a fill
portfolio.py makes whose legs are all round-off (<= MIN_LEG) is not sent, and the books then differ by its gas alone
(the value-ratio bound of ``scripts/nautilus_parity_real.py``); an order Nautilus lists that portfolio.py does not
must fill nothing.

    uv run python scripts/nautilus_portfolio_parity_real.py [--interval 1d] [--sources KRAKEN,BINANCE]
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from lab.data.catalog import snapshot_id
from lab.data.panel import load_panel
from lab.runner import nautilus_portfolio as npf
from lab.runner import portfolio as pf
from lab.runner.reference import Costs

LAST_TRAIN_CLOSE = "2023-01-01"
COLS = ["ret", "position", "turnover", "cost", *pf.WEIGHT_COLUMNS]


def cases(per_day: int) -> list[tuple[str, object, dict]]:
    steady = pf.risk_limits("steady")  # the limits as read from config/risk_levels.yaml, never typed
    return [
        (
            "50/50 BTC/ETH, band 5%, checked daily",
            pf.rebalance,
            {"w_btc": 0.5, "w_eth": 0.5, "band": 0.05, "every": per_day},
        ),
        (
            "Steady-like 35/25/40, band 3%, weekly, Steady limits",
            pf.rebalance,
            {
                "w_btc": 0.35,
                "w_eth": 0.25,
                "band": 0.03,
                "every": 7 * per_day,
                "min_cash": steady["min_cash"],
                "max_coin": steady["max_coin"],
                "headroom": 0.02,
            },
        ),
        (
            "40/40/20 at 60 random closes, seed 7",
            pf.random_rebalance,
            {"w_btc": 0.4, "w_eth": 0.4, "n_rebalances": 60, "seed": 7},
        ),
    ]


def sharpe(ret: np.ndarray, per_year: float) -> float:
    return float(ret.mean() / ret.std(ddof=1) * np.sqrt(per_year))


def compare(label: str, ref: pd.DataFrame, nt: pd.DataFrame) -> tuple[float, str, list[str]]:
    """(largest difference up to the first documented skip, a note, the disagreements found)."""
    problems = []
    ro, no = set(ref.attrs["orders"].tolist()), set(nt.attrs["orders"].tolist())
    rf, nf = set(ref.attrs["fills"]["bar"].tolist()), set(nt.attrs["fills"]["bar"].tolist())
    if ro - no:
        problems.append(f"{label}: portfolio.py ordered at closes {sorted(ro - no)[:5]} and Nautilus did not")
    if {t + 1 for t in no - ro} & nf:
        problems.append(f"{label}: an extra Nautilus order filled")
    if nf - rf:
        problems.append(f"{label}: Nautilus filled on bars {sorted(nf - rf)[:5]} and portfolio.py did not")
    skipped = sorted(rf - nf)
    turnover = ref["turnover"].to_numpy()
    if any(turnover[t] > 2 * npf.MIN_LEG for t in skipped):
        problems.append(f"{label}: Nautilus skipped real fills on bars {skipped[:5]}")
    upto = skipped[0] if skipped else len(ref)
    diff = float(np.abs(nt[COLS].to_numpy()[:upto] - ref[COLS].to_numpy()[:upto]).max())
    note = ""
    if skipped:
        ratio = np.prod(1 + nt["ret"].to_numpy()) / np.prod(1 + ref["ret"].to_numpy())
        g = ref["cost"].to_numpy()[skipped]
        expected = 1 / np.prod(1 - g)
        bound = g.sum() * nt["cost"].to_numpy()[upto:].sum() + npf.TOL
        off = abs(ratio / expected - 1)
        if off > bound:
            problems.append(f"{label}: value ratio {ratio} vs the skipped gas {expected}, bound {bound:.1e}")
        note = f"  ({len(skipped)} round-off fill(s) skipped from bar {upto}: off its gas by {off:.1e} <= {bound:.1e})"
    extra = len(no - ro)
    if extra:
        note += f"  ({extra} extra order(s) that filled nothing)"
    if diff > npf.TOL:
        problems.append(f"{label}: the engines differ by {diff:.3e} > {npf.TOL}")
    return diff, note, problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--interval", default="1d", choices=["1d", "1h"])
    parser.add_argument("--sources", default="KRAKEN,BINANCE")
    args = parser.parse_args()
    per_day, per_year = (1, 365) if args.interval == "1d" else (24, 365 * 24)
    cut = pd.Timestamp(LAST_TRAIN_CLOSE, tz="UTC")
    problems: list[str] = []
    timing = {"portfolio.py": [], "Nautilus": []}
    print(f"snapshot {snapshot_id()}, interval {args.interval}, train closes up to {LAST_TRAIN_CLOSE}")
    for source in args.sources.split(","):
        panel = load_panel(source, args.interval, last_close=LAST_TRAIN_CLOSE)
        if panel.index[-1] > cut:
            raise SystemExit("read past the train window")
        print(
            f"\n{source} {args.interval}: {len(panel)} closes {panel.index[0]:%Y-%m-%d %H:%M} .. "
            f"{panel.index[-1]:%Y-%m-%d %H:%M}, panel snapshot {panel.attrs['snapshot_id']}"
        )
        print(
            f"{'setting':54} {'costs':5} {'fills':>6} {'Sharpe ref':>10} {'Sharpe NT':>10} {'max |diff|':>11} "
            f"{'ref s/run':>9} {'NT s/run':>8}"
        )
        for label, rule, params in cases(per_day):
            for k, costs in (("1x", Costs.from_yaml()), ("2x", Costs.from_yaml().stressed())):
                start = time.perf_counter()
                ref = rule(params, panel, costs)
                t_ref = time.perf_counter() - start
                start = time.perf_counter()
                nt = npf.run(rule, params, panel, costs)
                t_nt = time.perf_counter() - start
                timing["portfolio.py"].append(t_ref)
                timing["Nautilus"].append(t_nt)
                diff, note, found = compare(f"{source} {args.interval} {label} {k}", ref, nt)
                problems += found
                s_ref, s_nt = sharpe(ref["ret"].to_numpy(), per_year), sharpe(nt["ret"].to_numpy(), per_year)
                print(
                    f"{label:54} {k:5} {nt.attrs['n_trades']:>6} {s_ref:>10.4f} {s_nt:>10.4f} {diff:>11.1e} "
                    f"{t_ref:>9.3f} {t_nt:>8.3f}{note}"
                )
    print()
    for engine, seconds in timing.items():
        mean = float(np.mean(seconds))
        print(
            f"{engine:13} {mean:.3f} s per run ({args.interval}), about {3600 / mean:,.0f} runs per hour per core"
        )
    if problems:
        print("\nDISAGREEMENTS:")
        for p in problems:
            print(" ", p)
        raise SystemExit(1)
    print("\nno disagreement")


if __name__ == "__main__":
    main()
