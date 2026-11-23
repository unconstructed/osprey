"""Amendment A0's procedure controls for trend-steady (PLAN.md section 9; stop rules 15 and 17). SYNTHETIC ONLY.

Never reads the catalog. Writes only into a scratch folder (never results/trend-steady or anywhere in the repo):

    uv run python research/trend-steady/controls.py --out-dir <scratch> [--workers 2]
    uv run python research/trend-steady/controls.py --out-dir <scratch> --fast        # tests only: tiny sizes

Before any panel is built it re-times the built code and projects A0's cost (stop rule 17): above 120 CPU-minutes
it refuses (exit 2, nothing written); a ``--fast`` run records the projection and never refuses. Then, on 20
positive-control panels (``synthetic_market(2190, seed=1000 + j, start="2017-01-02")``) and 20 negative-control
panels (``shuffled_market`` of those markets, seed j), the seed-A train pipeline: 5 fold studies at N trials, H0,
R_0 and its guarded shifts, N0, P, E1 and E2, and the stop-loss variant at its three levels with R_0^phi, its
shifts, N0^phi, SL-E1, SL-E2, its placebo stops and SL-T. And the one-off size check of E1 under volatility
clustering: the fixed rule (200, 0.10) at s = 0.50 on 1000 ``trend.garch_panel`` panels, R_0 against its 207 guarded
shifts. Reported: power, false positives (the plain rule, the variant per level, SL-T per level), E1's and SL-E1's
own counts, and the size check; 3 or more false positives in 20 (or more than 67 of 1000) is stop rule 15, power
below 4 of 20 an owner alarm. These panels are not trials and enter no count.
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
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner.portfolio import make_panel
from lab.search.walkforward import walk_forward_optimize
from lab.validation.splits import walk_forward


def _study_module():
    name = "trend_steady_study"
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
    fn = partial(T.trend_backtest, limits=limits, costs=costs)
    folds = walk_forward(len(panel), train_size=T.FOLD_ROWS, test_size=T.FOLD_ROWS, expanding=True)
    windows = T.fold_windows(panel.index)
    cfg = S.search_config(S.SEEDS["A"], S.Settings(n_trials=sizes.n_trials))
    name = f"a0-{kind}-{j:02d}-s0"
    wf = walk_forward_optimize(
        name,
        fn,
        list(T.SPECS),
        panel,
        folds,
        Path(out) / "studies",
        cfg,
        warmup=T.WARMUP,
        context={"a0": name},
    )
    params = [
        S.plain_params({n: wf["folds"].iloc[i][f"p_{n}"] for n in T.PARAM_NAMES}) for i in range(len(windows))
    ]
    b = S.plain_bundle(
        panel, windows, params, limits=limits, costs1=costs, costs2=None, offsets="guarded", x=False
    )
    e1 = S.e1(b)
    e2 = T.e2_test(b["S"], b["N0"], n_resamples=sizes.bootstrap_resamples)
    power = T.power_count([r.attrs["z"] for r in b["runs"]], windows, panel.index)
    levels = {}
    for phi in T.STOP_LEVELS:
        sb = S.stop_bundle(
            b, phi, limits=limits, costs1=costs, costs2=None, windows=windows, offsets="guarded", x=False
        )
        sl_e1 = S.e1(sb)
        sl_t = T.e1_test(sb["R0"].to_numpy(dtype=float), sb["placebos"], b["W"])
        sl_e2 = T.e2_test(sb["S"], sb["N0"], n_resamples=sizes.bootstrap_resamples)
        levels[f"{phi:.2f}"] = {
            "triggered": T.triggered(sb["S"].to_numpy(), b["S"].to_numpy()),
            "SL-E1": sl_e1["holds"],
            "SL-E2": sl_e2["holds"],
            "SL-T": sl_t["holds"],
            "sl_e1_rank_p": sl_e1["rank_p"],
            "sl_t_rank_p": sl_t["rank_p"],
            "sl_e2_p": sl_e2["p"],
        }
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
        "switches": power["total"],
        "levels": levels,
    }


def vol_check(j: int, config_dir) -> dict:
    """One panel of the size check under volatility clustering (section 9, M21), built as the slow calibration test
    builds its panels' R_0: the fixed rule in H0 as one span, its schedule over the fold layout's check closes, scored
    on the kept rows against its 207 guarded shifts at 1x, E1's rank-p rule."""
    limits = sd.steady_limits(config_dir)
    costs = S.costs_for(config_dir)
    panel = T.garch_panel(j)
    idx = panel.index
    windows = T.fold_windows(idx)
    kept_rows = np.concatenate([np.flatnonzero((idx > w.t0) & (idx <= w.last)) for w in windows])
    p = S.A0_VOL_POINT
    z = T.trend_states(panel, p["lookback"], p["buffer"]).z
    sch = T.stitched_schedule(
        idx, windows, [z[: idx.get_loc(w.last) + 1] for w in windows], [p["crypto_share"]] * 5
    )
    offsets = T.guarded_offsets(len(sch.checks)).tolist()
    series = {
        u: T.run_span(panel, sch, limits=limits, costs=costs, u=u)["ret"].to_numpy()[kept_rows]
        for u in [0, *offsets]
    }
    res = T.e1_test(series[0], series, len(sch.checks))
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
        "levels": {},
    }
    for level in (f"{phi:.2f}" for phi in T.STOP_LEVELS):
        out["levels"][level] = {
            "false_positives": sum(r["levels"][level]["SL-E1"] and r["levels"][level]["SL-E2"] for r in neg),
            "sl_t_false_positives": sum(r["levels"][level]["SL-T"] for r in neg),
            "sl_e1_alone": {
                "negative": sum(r["levels"][level]["SL-E1"] for r in neg),
                "positive_share": float(np.mean([r["levels"][level]["SL-E1"] for r in pos])),
            },
            "triggered": {
                "positive": sum(r["levels"][level]["triggered"] for r in pos),
                "negative": sum(r["levels"][level]["triggered"] for r in neg),
            },
        }
    out["vol_check"] = {"panels": len(vol), "passes": sum(v["holds"] for v in vol), "limit": S.A0_VOL_MAX}
    out["vol_check"]["holds"] = out["vol_check"]["passes"] <= S.A0_VOL_MAX
    alarms = [out["false_positives"] >= S.A0_ALARM_FP]
    for lv in out["levels"].values():
        alarms += [lv["false_positives"] >= S.A0_ALARM_FP, lv["sl_t_false_positives"] >= S.A0_ALARM_FP]
    out["stop_rule_15"] = bool(any(alarms) or not out["vol_check"]["holds"])
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
    T.check_feasibility(limits)
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
        f"{summary['false_positives']}/{summary['negative_panels']}, vol check {summary['vol_check']['passes']}/"
        f"{summary['vol_check']['panels']}; stop rule 15: {summary['stop_rule_15']}; power alarm: {summary['power_alarm']}",
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
