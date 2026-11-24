"""Amendment A0's procedure controls for downvol-steady (PLAN.md section 9; stop rules 15 and 17). SYNTHETIC ONLY.

Never reads the catalog. Writes only into a scratch folder (never results/downvol-steady or anywhere in the repo):

    uv run python research/downvol-steady/controls.py --out-dir <scratch> [--workers 2]
    uv run python research/downvol-steady/controls.py --out-dir <scratch> --fast        # tests only: tiny sizes

Before any panel is built it re-times the built code and projects A0's cost (stop rule 17): above 120 CPU-minutes
it refuses (exit 2, nothing written); a ``--fast`` run records the projection and never refuses. Then (section 9,
VP 9's three control sets, run on the downside-volatility rule, E1 on the q-only shifts of amendment M1):
- **positive controls:** ``make_panel(synthetic_market(2190, seed=1000 + j, start="2017-01-02"))``, j = 0..19 (volatility
  clustering and regimes);
- **negative controls:** ``shuffled_market`` of each positive market (seed j), which destroys volatility clustering;
- on each, the seed-A train pipeline: 5 fold studies at N trials, H0, R_0 and its 207 guarded q-only shifts, N0, P,
  E1, E2;
- **volatility clustering with no momentum** (a description, no alarm): the fixed rule (30, 0.60, 0.50) on 200
  ``trend.garch_panel`` panels (j = 0..199), R_0 against its 207 guarded q-only shifts (one s, so they are the
  whole-schedule shifts bit for bit); E1's pass rate is the power where the mechanism is real.
Reported: power (E1, E2 and P on the positive panels), false positives (E1 and E2 on the negative panels), E1's own
counts next to them, and the clustering pass rate. 3 or more false positives in 20 is stop rule 15; power below 4 of 20
is the owner alarm. These panels are not trials and enter no count.
"""

from __future__ import annotations

import argparse
import importlib.util
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path

import numpy as np

from lab.data.synthetic import shuffled_market, synthetic_market
from lab.runner import downvol as D
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.runner.portfolio import make_panel
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward


def _study_module():
    name = "downvol_steady_study"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("study.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


S = _study_module()


@dataclass(frozen=True)
class Sizes:
    panels: int = S.A0_PANELS
    vol_panels: int = S.A0_VOL_PANELS
    n_trials: int = S.PLAN_SETTINGS.n_trials  # one N for A0 and run 0 (amendment A1 sets it)
    bootstrap_resamples: int = S.PLAN_SETTINGS.bootstrap_resamples


PLAN_SIZES = Sizes()
FAST_SIZES = Sizes(panels=1, vol_panels=2, n_trials=10, bootstrap_resamples=200)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True, help="a scratch folder outside the repo")
    ap.add_argument(
        "--config-dir", default=None, help="folder with costs.yaml and risk_levels.yaml (default config/)"
    )
    ap.add_argument("--workers", type=int, default=1, help="worker processes (default 1)")
    ap.add_argument(
        "--fast", action="store_true", help="tests only: tiny sizes; the projection is recorded only"
    )
    return ap.parse_args(argv)


def control_panel(kind: str, j: int):
    """Positive control j, or the negative control built from it (section 9)."""
    market = synthetic_market(2190, seed=1000 + j, start="2017-01-02")
    if kind == "negative":
        market = shuffled_market(market, seed=j)
    return make_panel(market, snapshot_id="synthetic")


def pipeline(task: tuple) -> dict:
    """The seed-A train pipeline on one control panel (section 9)."""
    kind, j, out, sizes, config_dir = task
    panel = control_panel(kind, j)
    limits = sd.steady_limits(config_dir)
    costs = S.costs_for(config_dir)
    fn = partial(D.downvol_backtest, limits=limits, costs=costs)
    folds = walk_forward(len(panel), train_size=T.FOLD_ROWS, test_size=T.FOLD_ROWS, expanding=True)
    windows = T.fold_windows(panel.index)
    cfg = S.search_config(S.SEEDS["A"], S.Settings(n_trials=sizes.n_trials))
    name = f"a0-{kind}-{j:02d}-s0"
    wf = walk_forward_optimize(
        name,
        fn,
        list(V.SPECS),
        panel,
        folds,
        Path(out) / "studies",
        cfg,
        warmup=T.WARMUP,
        context={"a0": name},
    )
    params = [
        S.plain_params({n: wf["folds"].iloc[i][f"p_{n}"] for n in V.PARAM_NAMES}) for i in range(len(windows))
    ]
    b = S.plain_bundle(
        panel, windows, params, limits=limits, costs1=costs, costs2=None, offsets="guarded", x=False
    )
    e1 = S.e1(b)
    e2 = T.e2_test(b["S"], b["N0"], n_resamples=sizes.bootstrap_resamples)
    power = V.power_count([r.attrs["share"] for r in b["runs"]], windows, panel.index)
    return {
        "kind": kind,
        "j": j,
        "params": params,
        "W": b["W"],
        "E1": e1["holds"],
        "E2": e2["holds"],
        "P": power["holds"],
        "e1_rank_p": e1["rank_p"],
        "e2": {"d": e2["d"], "p": e2["p"]},
        "changes": power["total"],
    }


def vol_check(j: int, config_dir) -> dict:
    """One volatility-clustering panel (section 9), built as the slow calibration test builds its panels' R_0: the
    fixed rule in H0 as one span, its schedule over the fold layout's check closes, scored on the kept rows against its
    207 guarded q-only shifts at 1x, E1's rank-p rule."""
    limits = sd.steady_limits(config_dir)
    costs = S.costs_for(config_dir)
    panel = T.garch_panel(j)
    idx = panel.index
    windows = T.fold_windows(idx)
    kept_rows = np.concatenate([np.flatnonzero((idx > w.t0) & (idx <= w.last)) for w in windows])
    p = S.A0_VOL_POINT
    path = D.downvol_path(panel, p["lookback"], p["target_vol"], p["crypto_share"])
    ends = [idx.get_loc(w.last) + 1 for w in windows]
    steps = D.stitched_steps(
        idx,
        windows,
        [path.z[:e] for e in ends],
        [path.share[:e] for e in ends],
        [path.q[:e] for e in ends],
        [p["crypto_share"]] * len(windows),
    )
    w = len(steps.q)
    series = {
        u: D.run_q_shift(panel, steps, limits=limits, costs=costs, u=u)["ret"].to_numpy()[kept_rows]
        for u in [0, *T.guarded_offsets(w).tolist()]
    }
    res = T.e1_test(series[0], series, w)
    return {"j": j, "holds": res["holds"], "rank_p": res["rank_p"]}


def summarize(results: list[dict], vol: list[dict]) -> dict:
    pos = [r for r in results if r["kind"] == "positive"]
    neg = [r for r in results if r["kind"] == "negative"]
    out = {
        "positive_panels": len(pos),
        "negative_panels": len(neg),
        "power": sum(r["E1"] and r["E2"] and r["P"] for r in pos),
        "false_positives": sum(r["E1"] and r["E2"] for r in neg),
        "e1_alone": {
            "negative": sum(r["E1"] for r in neg),
            "positive_share": float(np.mean([r["E1"] for r in pos])),
        },
        "e2_alone": {
            "negative": sum(r["E2"] for r in neg),
            "positive_share": float(np.mean([r["E2"] for r in pos])),
        },
    }
    out["vol_clustering"] = {
        "panels": len(vol),
        "e1_passes": sum(v["holds"] for v in vol),
        "pass_rate": float(np.mean([v["holds"] for v in vol])),
        "note": "power where the mechanism is real (a description; no alarm)",
    }
    out["stop_rule_15"] = bool(out["false_positives"] >= S.A0_ALARM_FP)
    out["power_alarm"] = bool(out["power"] < S.A0_POWER_MIN)
    return out


def run(args) -> int:
    out = Path(args.out_dir)
    S.check_out_dir(out)
    if args.workers < 1:
        raise S.Refusal(f"--workers {args.workers}: at least 1")
    if (out / "start.json").exists():
        raise S.Refusal(
            f"{out / 'start.json'} exists: A0 runs once (its controls are never rerun with other seeds)"
        )
    config_dir = Path(args.config_dir) if args.config_dir else None
    limits = sd.steady_limits(config_dir)
    V.check_feasibility(limits)
    sizes = FAST_SIZES if args.fast else PLAN_SIZES
    timing_settings = S.FAST if args.fast else S.PLAN_SETTINGS
    try:
        timing = S.measure_timing(limits, S.costs_for(config_dir), timing_settings, sizes.n_trials)
    except Exception as exc:
        raise S.Refusal(f"stop rule 17: the re-timing failed: {type(exc).__name__}: {exc}") from exc
    proj = S.projection(timing, S.a0_counts(sizes.panels, sizes.vol_panels), T.CONTROLS_BUDGET_MINUTES)
    if not args.fast and not proj["allows"]:
        raise S.Refusal(
            f"stop rule 17: A0's projection is {proj['cpu_minutes']:.1f} CPU-minutes, above "
            f"{T.CONTROLS_BUDGET_MINUTES}: ask the owner"
        )
    hashes = S.file_hashes(config_dir)
    start = {
        "utc": S.utc_now(),
        "script": "controls.py",
        "label": "SYNTHETIC procedure controls (amendment A0); not results",
        "git": S.git_state(),
        "config_hash": S.config_hash(hashes),
        "file_hashes": hashes,
        "sizes": asdict(sizes),
        "fast": bool(args.fast),
        "workers": args.workers,
        "timing": timing,
        "projection": proj,
    }
    S.write_json(out / "start.json", start)
    print(
        f"A0 started: projection {proj['cpu_minutes']:.1f} CPU-minutes (budget {T.CONTROLS_BUDGET_MINUTES})",
        flush=True,
    )
    tasks = [
        (kind, j, str(out), sizes, config_dir)
        for kind in ("positive", "negative")
        for j in range(sizes.panels)
    ]
    t = time.time()
    if args.workers == 1:
        results = [pipeline(task) for task in tasks]
        vol = [vol_check(j, config_dir) for j in range(sizes.vol_panels)]
    else:
        with ProcessPoolExecutor(args.workers, mp_context=mp.get_context("fork")) as pool:
            results = list(pool.map(pipeline, tasks))
            vol = list(pool.map(partial(vol_check, config_dir=config_dir), range(sizes.vol_panels)))
    summary = summarize(results, vol)
    S.write_json(
        out / "controls.json",
        {
            "start": start,
            "summary": summary,
            "panels": results,
            "vol_check": vol,
            "runtime_s": time.time() - t,
        },
    )
    print(
        f"A0 done in {time.time() - t:.1f}s: power {summary['power']}/{summary['positive_panels']}, false positives "
        f"{summary['false_positives']}/{summary['negative_panels']}, clustering E1 "
        f"{summary['vol_clustering']['e1_passes']}/{summary['vol_clustering']['panels']}; stop rule 15: "
        f"{summary['stop_rule_15']}; power alarm: {summary['power_alarm']}",
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
