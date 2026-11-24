"""Amendment A1's throughput rule for downvol-steady (PLAN.md section 7, TP 7). SYNTHETIC ONLY.

Never reads the catalog. Writes only ``throughput.json`` into a scratch folder (never results/downvol-steady or the
repo):

    uv run python research/downvol-steady/throughput.py --out-dir <scratch>

It times one 200-trial study of the built adapter (``lab.runner.downvol.downvol_backtest``, ``n_workers = 1``, the box
of section 5) on ``make_panel(synthetic_market(2190, seed=21, start="2017-01-02"))``, in wall and CPU seconds, and the
median of 20 full-length backtests at a typical and a busy point. The rule: N = 200 if 12 x the study's time is at most
60 CPU-minutes; otherwise the largest multiple of 25 that fits; below 50, ask the owner (stop rule 3). It flags a redo
when the built adapter's single backtest is more than 2x trend-steady's stand-in (0.0131 s, TP appendix B;
INTERPRETATIONS["throughput_redo"]). It also writes run 0's and A0's projections (stop rule 17) from these timings.
The full tier's wall time is measured separately (a pytest run) and written into A1 by hand.
"""

from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
import tempfile
import time
from functools import partial
from pathlib import Path

import numpy as np

from lab.runner import downvol as D
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.search.study import SearchConfig, run_study


def _study_module():
    name = "downvol_steady_study"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("study.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


S = _study_module()
STAND_IN_BACKTEST_S = 0.0131  # trend-steady's stand-in, TP appendix B (INTERPRETATIONS["throughput_redo"])
STUDIES = 12
POINTS = {
    "typical": dict(S.A0_VOL_POINT),
    "busy": {"lookback": 10, "target_vol": 0.30, "crypto_share": 0.6},
}


def rule_n(study_cpu_s: float, budget_minutes: float = T.RUN_BUDGET_MINUTES, n: int = 200) -> dict:
    """Section 7's rule: N = 200 if 12 x the 200-trial study fits the budget, else the largest multiple of 25 that
    fits; below 50, ask the owner."""
    per_trial = study_cpu_s / n
    fits = int(budget_minutes * 60.0 / (STUDIES * per_trial)) if per_trial > 0 else n
    chosen = n if STUDIES * study_cpu_s <= budget_minutes * 60.0 else (min(fits, n) // 25) * 25
    return {"N": chosen, "ask_owner": chosen < 50, "twelve_studies_cpu_minutes": STUDIES * study_cpu_s / 60.0}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--trials", type=int, default=200, help="tests only: a smaller study")
    ap.add_argument("--reps", type=int, default=20, help="tests only: fewer repetitions")
    return ap.parse_args(argv)


def run(args) -> int:
    out = Path(args.out_dir)
    S.check_out_dir(out)
    config_dir = Path(args.config_dir) if args.config_dir else None
    limits = sd.steady_limits(config_dir)
    V.check_feasibility(limits)
    costs = S.costs_for(config_dir)
    panel = S.timing_panel()
    fn = partial(D.downvol_backtest, limits=limits, costs=costs)
    record: dict = {
        "label": "SYNTHETIC throughput (amendment A1); not results",
        "python": platform.python_version(),
    }
    for name, params in POINTS.items():
        ts = []
        for _ in range(args.reps):
            c = time.perf_counter()
            fn(params, panel)
            ts.append(time.perf_counter() - c)
        record[f"backtest_{name}_median_s"] = float(np.median(ts))
    with tempfile.TemporaryDirectory() as tmp:
        w0, c0 = time.perf_counter(), time.process_time()
        trials = run_study(
            "throughput",
            fn,
            list(V.SPECS),
            panel,
            tmp,
            SearchConfig(n_trials=args.trials, n_workers=1, seed=0),
        )
        wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    scale = 200 / args.trials
    record["study"] = {
        "trials": len(trials),
        "states": trials["state"].value_counts().to_dict(),
        "wall_s": wall,
        "cpu_s": cpu,
        "cpu_s_per_200": cpu * scale,
    }
    record["rule"] = rule_n(cpu * scale)
    record["redo"] = bool(record["backtest_typical_median_s"] > 2 * STAND_IN_BACKTEST_S)
    timing = S.measure_timing(
        limits, costs, S.Settings(timing_trials=args.trials, timing_reps=args.reps), 200
    )
    record["projection_run0"] = S.projection(timing, S.run_counts(), T.RUN_BUDGET_MINUTES)
    record["projection_a0"] = S.projection(timing, S.a0_counts(), T.CONTROLS_BUDGET_MINUTES)
    record["timing"] = timing
    S.write_json(out / "throughput.json", record)
    print(
        f"A1: 200-trial study {cpu * scale:.1f} CPU-s; N = {record['rule']['N']}; backtest "
        f"{record['backtest_typical_median_s'] * 1e3:.1f} ms; run 0 projection "
        f"{record['projection_run0']['cpu_minutes']:.1f} CPU-minutes; A0 {record['projection_a0']['cpu_minutes']:.1f}",
        flush=True,
    )
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except S.Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
