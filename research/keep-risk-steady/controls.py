"""Amendment A0's synthetic pre-check for keep-risk-steady (PLAN.md section 13; stop rules 7 and 9). SYNTHETIC ONLY.

Never reads the catalog. Writes only into a scratch folder (never results/keep-risk-steady or anywhere in the repo):

    uv run python research/keep-risk-steady/controls.py --out-dir <scratch> [--workers 2]
    uv run python research/keep-risk-steady/controls.py --out-dir <scratch> --second-range   # after a first alarm
    uv run python research/keep-risk-steady/controls.py --out-dir <scratch> --fast           # tests only: tiny sizes

Before any panel is built it re-times the built code (``run.measure_throughput``) and projects A0's cost: at most 300
CPU-minutes with 100 panels a set starts with 100; else at most 300 with 80 panels a set starts with 80 (the plan's
pinned fallback); else it refuses (exit 2, nothing written). A ``--fast`` run records the projection and never refuses.

Then, on each panel of the five sets (100 each; section 13's seeds, all streams from 200000 on, or + 100000 with
``--second-range``), at the one mix (s 0.50, f 0.50), the four w and 14 returns: the rule, N and X on the 49 Kraken
windows of the train grid, the rule, N and X on the full span with every guarded copy and its own same-average mix,
RISK-X with 10,000 resamples (one index set, seed 0, as run 0), E1, Holm over the four w, the labels and D1 at that
mix. Reported: false CALMER and false defaults on NW, NS and NC, E1's size on NC, the resampling's honesty at the
boundary on PG, NW and NC, and the power on PG and PR; the alarms A0-1 .. A0-4 (exit 3 when one fires). These panels
are not trials and enter no count.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import multiprocessing as mp
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.synthetic import shuffled_market, synthetic_market
from lab.runner import holdmix as H
from lab.runner import keeprisk as K
from lab.runner import protect as P
from lab.runner import trend as T
from lab.runner.portfolio import make_panel


def _run_module():
    name = "keep_risk_steady_run"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("run.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


R = _run_module()

SETS = ("PG", "PR", "NW", "NS", "NC")
POSITIVE = ("PG", "PR")
NEGATIVE = ("NW", "NS", "NC")
ONE_TRUTH = ("PG", "NW", "NC")  # the boundary check (PR and NS panels each have their own truth)
MIX = (0.50, 0.50)
SECOND_RANGE = 100_000
PANELS = 100
FALLBACK_PANELS = 80
# Section 13's seeds: the j-th panel's generator arguments (garch_panel(j) draws from default_rng(10000 + j))
SEEDS = {
    "PG": 200_000,  # trend.garch_panel(200000 + j): streams 210000 + j
    "PR": 220_000,  # synthetic_market(seed=220000 + j)
    "NW": 230_000,  # trend.random_walk_panel(230000 + j)
    "NS": 240_000,  # synthetic_market(seed=240000 + j), shuffled with seed 241000 + j
    "NS_shuffle": 241_000,
    "NC": 250_000,  # prices trend.garch_panel(250000 + j): streams 260000 + j
    "NC_schedule": 260_000,  # the q schedule on trend.garch_panel(260000 + j): streams 270000 + j
}
GARCH_STREAM = 10_000  # trend.garch_panel(j) draws from default_rng(10000 + j)
# Section 2: the streams already used (default_rng seeds), which A0 must not reuse
PRIOR_STREAMS = (
    *range(80_000, 80_020),  # garch_panel j 70000-70019
    *range(71_000, 71_020),
    *range(73_000, 73_020),
    *range(73_500, 73_520),
    *range(72_000, 72_020),
    0,
    *range(10_000, 18_720),  # the design note: garch_panel up to 8719
    *range(0, 9_930),  # synthetic_market up to 9929
    *range(50_000, 50_200),
    *range(91_000, 91_020),
    *range(20_000, 70_000),  # reserved
    *range(80_000, 99_001),  # statistics-first: garch_panel j 70000-89000
    *range(85_000, 97_960),
    70_000,
    100_000,
    100_100,
    92_000,
    93_000,
)
READINGS = {
    "resampling_seed": "Each panel's RISK-X uses run 0's procedure, one index set from default_rng(0) (section 9.2) "
    "over the 2189 return rows of the train grid, shared by every panel; the disjointness of section 13 is the "
    "panels' market streams'",
    "fallback": "100 panels a set when the projection at 100 is at most 300 CPU-minutes; else 80 when the projection "
    "at 80 is; else refused (stop rule 7)",
    "alarm_limits": "'more than 10 of 100' and 'more than 30 of 400' as more than n // 10 and more than 3 n // 10 "
    "(80 panels: 8 and 24)",
    "boundary": "V-bar is the mean (math.fsum) of the other panels' finite V at that w; a panel with a MISSING V is "
    "not tested; each tail's count is pooled over the four w",
    "nc_windows": "On NC the q of each window (its switch-on decision included) is computed on the schedule panel "
    "and run on the price panel's window",
    "copies": "The guarded copies' and their mixes' runs are measured by DD only (no fee check): A0 is a check of "
    "the statistics, not of the accounting, which run 0 checks on every run",
    "exit": "An alarm prints ALARM and exits 3 after writing a0.json; no alarm exits 0. The last line names the "
    "alarms ('A0 alarms: A0-<n>, ...') or prints run.py's pinned phrase 'A0 alarms: none' (stop rule 8's record)",
}


@dataclass(frozen=True)
class Sizes:
    panels: int = PANELS
    resamples: int = K.RESAMPLES
    copy_stride: int = 1
    windows: tuple[int, ...] = tuple(k for k, _, _ in P.rolling_windows("KRAKEN"))


PLAN_SIZES = Sizes()
FAST_SIZES = Sizes(panels=1, resamples=200, copy_stride=64, windows=(0, 24, 48))


def _relabel(market: dict) -> pd.DataFrame:
    grid = T.train_grid()
    frames = {}
    for asset, bars in market.items():
        frame = bars.copy()
        frame.index = grid
        frames[asset] = frame
    return make_panel(frames, snapshot_id="synthetic")


def build_panels(set_name: str, j: int, second: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(prices, signal) of panel j of a set (section 13's table): the signal is the prices except on NC."""
    add = SECOND_RANGE if second else 0
    if set_name == "PG":
        p = T.garch_panel(SEEDS["PG"] + add + j)
    elif set_name == "PR":
        p = _relabel(synthetic_market(2190, seed=SEEDS["PR"] + add + j, start="2017-01-02"))
    elif set_name == "NW":
        p = T.random_walk_panel(SEEDS["NW"] + add + j)
    elif set_name == "NS":
        market = synthetic_market(2190, seed=SEEDS["NS"] + add + j, start="2017-01-02")
        p = _relabel(shuffled_market(market, seed=SEEDS["NS_shuffle"] + add + j))
    elif set_name == "NC":
        prices = T.garch_panel(SEEDS["NC"] + add + j)
        return prices, T.garch_panel(SEEDS["NC_schedule"] + add + j)
    else:
        raise ValueError(f"unknown set {set_name!r}; expected one of {SETS}")
    return p, p


def streams(set_name: str, j: int, second: bool = False) -> list[int]:
    """The default_rng seeds panel j of a set draws from."""
    add = SECOND_RANGE if second else 0
    if set_name in ("PG", "NC"):
        out = [GARCH_STREAM + SEEDS[set_name] + add + j]
        if set_name == "NC":
            out.append(GARCH_STREAM + SEEDS["NC_schedule"] + add + j)
        return out
    if set_name == "NS":
        return [SEEDS["NS"] + add + j, SEEDS["NS_shuffle"] + add + j]
    return [SEEDS[set_name] + add + j]


# ------------------------------------------------------------------------------------------------ one panel

_CTX: dict = {}


def _dd(result: pd.DataFrame) -> float:
    return K.down_day(result["ret"].to_numpy()[1:])


def panel_result(set_name: str, j: int) -> dict:
    """Every number A0 needs from one panel (module docstring)."""
    ctx = _CTX
    sizes: Sizes = ctx["sizes"]
    lim, costs, idx = ctx["limits"], ctx["costs"], ctx["idx"]
    s, f = MIX
    prices, signal = build_panels(set_name, j, ctx["second"])
    sig = K.swing(signal, f)
    n = len(prices)
    windows, cells = [], []
    offsets = T.guarded_offsets(len(K.q_path(signal, K.W_VALUES[0], f, sigma=sig).checks))[
        :: sizes.copy_stride
    ]
    for w in K.W_VALUES:
        full = K.q_path(signal, w, f, sigma=sig)
        for k in sizes.windows:
            _, first, last = P.rolling_windows("KRAKEN")[k]
            piece = H.window_slice(prices, first, last, missing=H.MISSING_CLOSES["KRAKEN"])
            r0 = int(prices.index.get_loc(first))
            qp = K.q_path(signal, w, f, start=r0, stop=r0 + len(piece), sigma=sig)
            rule = K.run_rule(piece, qp, s, f, limits=lim, costs=costs)
            x = K.matched_share(s * qp.q)
            got = {
                kind: K.run_measures(res, costs, s=s, w=w)
                for kind, res in (
                    ("rule", rule),
                    ("N", K.run_yardstick(piece, s, f, limits=lim, costs=costs)),
                    ("X", K.run_yardstick(piece, x, f, limits=lim, costs=costs)),
                )
            }
            cmp_ = K.compare(got["rule"], got["N"], got["X"], None)
            windows.append(
                {"kind": "rule", "status": K.OK, "w": w, "s": s, "f": f, "window": k, **cmp_, "x": x}
            )
        rule = K.run_rule(prices, full, s, f, limits=lim, costs=costs)
        x = K.matched_share(s * full.q)
        x_run = K.run_yardstick(prices, x, f, limits=lim, costs=costs)
        K.run_yardstick(prices, s, f, limits=lim, costs=costs)  # N: one of the plan's 3 full-span runs
        rx = K.risk_x(rule["ret"].to_numpy()[1:], x_run["ret"].to_numpy()[1:], idx, keep=True)
        schedule = K.copy_schedule(full, s)
        vs = []
        for u in offsets.tolist():
            targets, share = K.shifted_copy(schedule, u, n, f)
            copy = K.ride_run(prices, targets, limits=lim, costs=costs)
            mix = K.run_yardstick(prices, K.matched_share(share), f, limits=lim, costs=costs)
            vs.append(K.ride_v(_dd(copy), _dd(mix)))
        ev = K.e1(K.ride_v(_dd(rule), _dd(x_run)), vs)
        steps = bool(full.q_on < 1.0 or (full.q_checks < 1.0).any())
        cells.append(
            {
                "w": w,
                "s": s,
                "f": f,
                "missing": rx["missing"] is not None,
                "failed": False,
                "steps": steps,
                "e1_rank_p": ev["rank_p"],
                "e1_holds": ev["holds"],
                **{k: rx[k] for k in ("V", "p_calm", "p_rough", "p_eq", "cost_flag")},
                "V_star": rx.get("V_star"),
            }
        )
    labelled = K.label_family(cells)
    frame = pd.DataFrame(windows)
    labels = pd.DataFrame([{k: c[k] for k in ("w", "s", "f", "label", "failed")} for c in labelled])
    decision = K.d1(frame, labels, settings=K.W_VALUES, mixes=(MIX,))
    by_w = {}
    for c, w in zip(labelled, K.W_VALUES, strict=True):
        part = frame[frame["w"] == w]
        by_w[w] = {
            **{k: c[k] for k in ("V", "p_calm", "p_rough", "p_eq", "e1_rank_p", "e1_holds", "holm", "label")},
            "V_star": c["V_star"],
            "calmer_windows": int((part["V_X"].to_numpy(dtype=float) < 0.0).sum()),
            "c_X_median": float(np.median(part["c_X"].to_numpy(dtype=float))),
        }
    return {"set": set_name, "j": j, "status": K.OK, "default": decision["default"], "by_w": by_w}


def run_panel(task: tuple[str, int]) -> dict:
    """One panel; a failure is recorded (its numbers MISSING) and the check goes on."""
    try:
        return panel_result(*task)
    except Exception as exc:
        return {
            "set": task[0],
            "j": task[1],
            "status": "failed",
            "error": f"{exc!r}",
            "tb": traceback.format_exc(),
        }


def _init(ctx: dict) -> None:
    _CTX.clear()
    _CTX.update(ctx)


# ------------------------------------------------------------------------------------------------ the summary


def alarm_limits(n_panels: int) -> dict:
    """READINGS["alarm_limits"]: more than n // 10 panels (A0-1 .. A0-3), more than 3 n // 10 tests (A0-4)."""
    return {"count": n_panels // 10, "boundary": (3 * n_panels) // 10}


def boundary_counts(panels: list[dict], resamples: int) -> dict:
    """The resampling's honesty at the boundary on one set (READINGS["boundary"]), pooled over the four w."""
    upper = lower = tests = 0
    for w in K.W_VALUES:
        vs = [p["by_w"][w]["V"] if p["status"] == K.OK else None for p in panels]
        for i, p in enumerate(panels):
            others = [v for jj, v in enumerate(vs) if jj != i and K._finite(v)]
            if not K._finite(vs[i]) or not others or p["by_w"][w]["V_star"] is None:
                continue
            vbar = math.fsum(others) / len(others)
            star = np.asarray(p["by_w"][w]["V_star"], dtype=float)
            tests += 1
            upper += int((1 + int((star >= vbar).sum())) / (resamples + 1) < K.ALPHA)
            lower += int((1 + int((star <= vbar).sum())) / (resamples + 1) < K.ALPHA)
    return {"upper": upper, "lower": lower, "tests": tests}


def summarize(results: list[dict], n_panels: int, resamples: int) -> dict:
    """A0's measures (section 13) and the alarms A0-1 .. A0-4 at their pinned limits."""
    by_set = {name: [r for r in results if r["set"] == name] for name in SETS}
    lim = alarm_limits(n_panels)

    def ok(rows):
        return [r for r in rows if r["status"] == K.OK]

    def any_label(r, label):
        return any(r["by_w"][w]["label"] == label for w in K.W_VALUES)

    out = {
        "panels": n_panels,
        "limits": lim,
        "failed": {s: len(by_set[s]) - len(ok(by_set[s])) for s in SETS},
    }
    out["false_calmer"] = {s: sum(any_label(r, K.CALMER) for r in ok(by_set[s])) for s in NEGATIVE}
    out["false_default"] = {s: sum(isinstance(r["default"], float) for r in ok(by_set[s])) for s in NEGATIVE}
    out["e1_size"] = {
        str(w): sum(bool(r["by_w"][w]["e1_holds"]) for r in ok(by_set["NC"])) for w in K.W_VALUES
    }
    out["boundary"] = {s: boundary_counts(by_set[s], resamples) for s in ONE_TRUTH}
    power = {}
    for s in POSITIVE:
        rows = ok(by_set[s])
        power[s] = {
            "e1": {str(w): sum(bool(r["by_w"][w]["e1_holds"]) for r in rows) for w in K.W_VALUES},
            "holm": {str(w): sum(bool(r["by_w"][w]["holm"]) for r in rows) for w in K.W_VALUES},
            "calmer_any": sum(any_label(r, K.CALMER) for r in rows),
            "default": {str(w): sum(r["default"] == w for r in rows) for w in K.W_VALUES},
            "labels": {
                str(w): {lab: sum(r["by_w"][w]["label"] == lab for r in rows) for lab in K.LABELS}
                for w in K.W_VALUES
            },
        }
    out["power"] = power
    alarms = []
    if any(v > lim["count"] for v in out["false_calmer"].values()):
        alarms.append("A0-1")
    if any(v > lim["count"] for v in out["false_default"].values()):
        alarms.append("A0-2")
    if any(v > lim["count"] for v in out["e1_size"].values()):
        alarms.append("A0-3")
    if any(max(b["upper"], b["lower"]) > lim["boundary"] for b in out["boundary"].values()):
        alarms.append("A0-4")
    out["alarms"] = alarms
    out["low_power"] = all(power[s]["calmer_any"] < lim["count"] for s in POSITIVE)
    return out


# ------------------------------------------------------------------------------------------------ the run


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True, help="a scratch folder outside the repo")
    ap.add_argument("--config-dir", default=None, help="folder with costs.yaml and risk_levels.yaml")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--fast", action="store_true", help="tests only: tiny sizes")
    ap.add_argument("--second-range", action="store_true", help="every seed + 100000 (after a first alarm)")
    return ap.parse_args(argv)


def choose_panels(a0_minutes: dict, fast: bool) -> int:
    """Stop rule 7 for A0 (READINGS["fallback"])."""
    if fast:
        return FAST_SIZES.panels
    for n in (PANELS, FALLBACK_PANELS):
        if a0_minutes[str(n)] <= R.A0_CPU_MINUTES_MAX:
            return n
    raise R.Refusal(
        f"stop rule 7: A0 projects {a0_minutes[str(FALLBACK_PANELS)]:.1f} CPU-minutes at {FALLBACK_PANELS} panels a "
        f"set, above {R.A0_CPU_MINUTES_MAX:g}: ask the owner"
    )


def run(args) -> int:
    out = Path(args.out_dir)
    R.check_out_dir(out)
    if args.workers < 1:
        raise R.Refusal(f"--workers {args.workers}: at least 1")
    config_dir = Path(args.config_dir) if args.config_dir else None
    limits = R.steady_limits(config_dir)
    timing = R.measure_throughput(limits, config_dir, R.TIMING_REPS_FAST if args.fast else R.TIMING_REPS)
    n_panels = choose_panels(timing["a0_cpu_minutes"], args.fast)
    base = FAST_SIZES if args.fast else PLAN_SIZES
    sizes = Sizes(
        panels=n_panels, resamples=base.resamples, copy_stride=base.copy_stride, windows=base.windows
    )
    start = {
        "utc": R.utc_now(),
        "script": "controls.py",
        "fast": bool(args.fast),
        "second_range": bool(args.second_range),
        "sizes": asdict(sizes),
        "timing": timing,
        "seeds": SEEDS,
        "readings": READINGS,
        "git": R.git_state(),
        "label": R.LABEL,
    }
    R.write_json(out / "start.json", start)
    t0 = time.time()
    ctx = {
        "sizes": sizes,
        "limits": {"min_cash": limits["min_cash"], "max_coin": limits["max_coin"]},
        "costs": R.cost_models(config_dir)[("1x", K.DEPOSIT)],
        "idx": K.index_set(len(T.train_grid()) - 1, resamples=sizes.resamples),
        "second": bool(args.second_range),
    }
    todo = [(name, j) for name in SETS for j in range(sizes.panels)]
    _init(ctx)
    if args.workers == 1:
        results = [run_panel(t) for t in todo]
    else:
        with ProcessPoolExecutor(
            max_workers=args.workers, mp_context=mp.get_context("fork"), initializer=_init, initargs=(ctx,)
        ) as pool:
            results = list(pool.map(run_panel, todo))
    summary = summarize(results, sizes.panels, sizes.resamples)
    rows = [
        {
            "set": r["set"],
            "j": r["j"],
            "status": r["status"],
            "default": str(r.get("default")),
            "w": w,
            **{k: v for k, v in r["by_w"][w].items() if k != "V_star"},
        }
        for r in results
        if r["status"] == K.OK
        for w in K.W_VALUES
    ]
    R.write_parquet(pd.DataFrame(rows), out / "panels.parquet")
    failures = [{k: r[k] for k in ("set", "j", "error", "tb")} for r in results if r["status"] != K.OK]
    R.write_json(out / "a0.json", {"summary": summary, "failures": failures, "runtime_s": time.time() - t0})
    alarms = f"A0 alarms: {', '.join(summary['alarms'])}" if summary["alarms"] else R.A0_NO_ALARM
    print(f"A0 ({sizes.panels} panels a set) done in {time.time() - t0:.1f}s. {alarms}")
    if summary["alarms"]:
        print(f"ALARM: {', '.join(summary['alarms'])} (stop rule 9: run 0 does not start)", file=sys.stderr)
        return 3
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except R.Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
