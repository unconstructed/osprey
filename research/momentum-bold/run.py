"""momentum-bold run 0 (and amendment runs): research/momentum-bold/PLAN.md, sections 3-12.

Scouting only (AGENTS.md hard rule 3). Train window only (closes up to 2023-01-01 00:00 UTC); no validate or test
look. ``--synthetic SEED [--fast]`` is a dry run on synthetic coins in a scratch folder; ``--time`` prints the CPU
projection (stop rule 7) from a synthetic timing panel and reads no bar.

Exit codes: 0 done, 2 refused at the start (nothing written), 3 stopped by a stop rule (recorded).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import CONFIG_DIR
from lab.data.external import HoldoutWindowError
from lab.runner import momentum as M
from lab.runner import steady
from lab.search.report import overfitting_report
from lab.search.space import Param
from lab.search.study import SearchConfig, load_trials
from lab.search.walkforward import walk_forward_optimize
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
STUDY = "momentum-bold"
DEFAULT_OUT = REPO / "results" / STUDY
DEFAULT_CATALOG = REPO / "data" / "catalog_bold"
LAST_CLOSE = pd.Timestamp("2023-01-01", tz="UTC")  # section 3: the last train close
DATA_END = pd.Timestamp("2024-07-01", tz="UTC")  # the loader's own refusal point
FIRST_CLOSE = pd.Timestamp("2017-08-18", tz="UTC")  # synthetic stand-in for BTCUSDT's first close
SNAPSHOT: dict | None = None  # section 3: written by amendment D1 (the data agent's snapshot) before run 0
CPU_MINUTES_MAX = 120.0  # stop rule 7
N_FOLDS, TEST_SIZE = 4, 365  # section 10
SEED = 0
STRESS = 2.0
MAX_AMENDMENTS = 2
TIMING_REPS = 3
TIMING_PARAMS = {"lookback": 91, "k": 10, "filter": "none"}
CONFIG_FILES = ("config/costs.yaml", "config/splits.yaml", "config/risk_levels.yaml")
SPECS = [
    Param("lookback", "cat", choices=M.LOOKBACKS),
    Param("k", "cat", choices=M.KS),
    Param("filter", "cat", choices=M.FILTERS),
]
B_PARAMS = {
    "B1": {"weights": {M.BTC: 1.0}, "every": None},
    "B2": {"weights": {M.BTC: 0.5}, "every": 30},
    "B3": {},
}
INTERPRETATIONS = {
    "panel": "the daily grid from the first close of any symbol to 2023-01-01 00:00 UTC; missing days stay NaN",
    "null_seed": "draw j of fold i uses seed 10000 (i + 1) + j",
    "strict_count": "every search trial + 4 plateau steps + 1 run at 2x costs",
    "e1": "rank p = (1 + #{draw Sharpe >= Sharpe(S)}) / (draws + 1); holds at p <= 0.05",
    "projection": "every backtest priced as one rule run on the timing panel",
}


@dataclass(frozen=True)
class Sizes:
    n_trials: int
    n_draws: int
    coins: int  # synthetic coins besides BTC, ETH and the 4 excluded ones
    timing_coins: int


PLAN_SIZES = Sizes(n_trials=60, n_draws=200, coins=40, timing_coins=400)
FAST = Sizes(n_trials=12, n_draws=20, coins=14, timing_coins=40)


class Refusal(Exception):
    pass


class Stop(Exception):
    def __init__(self, rule: str, message: str):
        super().__init__(f"stop rule {rule}: {message}")
        self.rule = rule


# ------------------------------------------------------------------------------------------- records


def frozen_paths() -> list[str]:
    lab = [
        f"lab/runner/{m}.py" for m in ("momentum", "portfolio", "reference", "interface", "steady")
    ] + ["lab/config.py", "lab/data/external.py", "lab/data/bold.py"]
    lab += sorted(str(p.relative_to(REPO)) for d in ("lab/search", "lab/validation") for p in (REPO / d).glob("*.py"))
    return [*lab, "research/momentum-bold/run.py", "research/momentum-bold/PLAN.md", *CONFIG_FILES]


def file_hashes(config_dir: Path | None) -> dict[str, str]:
    cfg = Path(config_dir or CONFIG_DIR)
    out = {}
    for rel in frozen_paths():
        path = cfg / Path(rel).name if rel in CONFIG_FILES else REPO / rel
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
    return out


def pinned_values() -> dict:
    return {
        "plan": asdict(PLAN_SIZES),
        "fast": asdict(FAST),
        "specs": [asdict(p) for p in SPECS],
        "engine": {
            k: getattr(M, k)
            for k in ("TOP_N", "VOLUME_DAYS", "MIN_HISTORY", "SMA_DAYS", "WEEKDAY", "HAIRCUT", "WARMUP", "E1_P")
        },
        "exclusions": {
            k: sorted(getattr(M, k)) for k in ("STABLECOINS", "FIAT", "WRAPPED_PEGGED", "LEVERAGED_UNDERLYINGS")
        },
        "run": [SEED, STRESS, N_FOLDS, TEST_SIZE, CPU_MINUTES_MAX, str(LAST_CLOSE), SNAPSHOT, B_PARAMS],
        "interpretations": INTERPRETATIONS,
    }


def config_hash(hashes: Mapping[str, str]) -> str:
    blob = json.dumps({"files": dict(sorted(hashes.items())), "pinned": pinned_values()}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def git_state(repo: Path = REPO) -> dict:
    def run(*args: str) -> str:
        res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {res.stderr.strip()}")
        return res.stdout

    changes = [x for x in run("status", "--porcelain", "--untracked-files=all").splitlines() if x]
    return {"commit": run("rev-parse", "HEAD").strip(), "dirty": bool(changes), "changes": changes[:50]}


def jsonable(x):
    if isinstance(x, Mapping):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, np.bool_ | bool):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, float | np.floating):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(obj), indent=1, sort_keys=True) + "\n")


def runlog_path(out: Path, synthetic: bool) -> Path:
    return (Path(out) / "tracked" if synthetic else HERE) / "RUNLOG.jsonl"


def append_runlog(path: Path, entry: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(jsonable(entry), sort_keys=True) + "\n")


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path) -> None:
    where = Path(out).resolve()
    if _inside(where, DEFAULT_OUT.resolve()) or _inside(where, REPO.resolve()):
        raise Refusal(f"--out-dir {out}: a dry run or the timing never writes into {DEFAULT_OUT} or the repo")


def check_real_paths(out: Path, config_dir: Path | None, catalog_dir: Path) -> None:
    if Path(out).resolve() != DEFAULT_OUT.resolve():
        raise Refusal(f"--out-dir {out}: a real run writes only to {DEFAULT_OUT}")
    if config_dir is not None and Path(config_dir).resolve() != (REPO / "config").resolve():
        raise Refusal(f"--config-dir {config_dir}: a real run reads config/ only")
    if Path(catalog_dir).resolve() != DEFAULT_CATALOG.resolve():
        raise Refusal(f"--catalog-dir {catalog_dir}: a real run reads only {DEFAULT_CATALOG}")


def check_layout(out: Path, k: int, synthetic: bool, runlog: Path) -> None:
    """Stop rule 6: run 0 runs once; amendment run k (1..2) needs run k-1's start record and a PLAN.md row."""
    data = "synthetic" if synthetic else "real"
    for line in (json.loads(x) for x in runlog.read_text().splitlines() if x.strip()) if runlog.is_file() else []:
        if line.get("run") == k and line.get("data") == data:
            raise Refusal(f"{runlog} already records {data} run {k}: a run number is never reused (stop rule 6)")
    if (Path(out) / f"run{k}").exists():
        raise Refusal(f"{Path(out) / f'run{k}'} exists: a run is never resumed or rerun (stop rule 6)")
    if k == 0:
        return
    if not 1 <= k <= MAX_AMENDMENTS:
        raise Refusal(f"--amendment {k}: amendment runs are numbered 1..{MAX_AMENDMENTS} (stop rule 6)")
    if not (Path(out) / f"run{k - 1}" / "start.json").is_file():
        raise Refusal(f"--amendment {k}: run {k - 1} has no start record")
    if not synthetic and f"- **Amendment run {k}**" not in PLAN.read_text():
        raise Refusal(f"--amendment {k}: PLAN.md section 12 has no dated '- **Amendment run {k}**' row")


# ------------------------------------------------------------------------------------------- the data


def synthetic_frames(seed: int, n_coins: int, last: pd.Timestamp = DATA_END) -> dict[str, pd.DataFrame]:
    """Synthetic daily coins in ``load_bold_daily``'s shape (dry runs, tests and the timing only): BTC and ETH from
    FIRST_CLOSE, ``n_coins`` coins listed on seeded dates (a quarter of them delisted before 2023), each with a
    few missing days, and four coins the universe excludes (a stablecoin, a leveraged token, a fiat and a wrapped
    coin) traded more than anything else."""
    rng = np.random.default_rng([seed, 12345])
    grid = pd.date_range(FIRST_CLOSE, last, freq="D", name="ts").as_unit("us")
    n = len(grid)
    market = rng.standard_t(4, n) * 0.025 + 0.0004
    names = ["BTC", "ETH", *(f"C{i:02d}" for i in range(n_coins)), "USDC", "BTCUP", "EUR", "WBTC"]
    frames = {}
    for i, base in enumerate(names):
        if base in ("BTC", "ETH", "USDC", "BTCUP", "EUR", "WBTC"):
            first, last_row = 0, n - 1
        else:
            first = int(rng.integers(0, int(n * 0.6)))
            last_row = n - 1 if rng.random() > 0.25 else int(rng.integers(first + 100, min(n - 1, 1960) + 1))
        beta = 1.0 if i < 2 else rng.uniform(0.8, 1.6)
        lr = beta * market + rng.standard_t(4, n) * rng.uniform(0.01, 0.05) + rng.normal(0.0, 0.001)
        if base in ("USDC", "EUR"):
            lr = rng.normal(0.0, 0.001, n)
        close = (30000.0 if i == 0 else rng.uniform(0.5, 2000.0)) * np.exp(np.cumsum(lr))
        prev = np.concatenate([[close[0]], close[:-1]])
        open_ = prev * np.exp(rng.normal(0.0, 0.002, n))
        high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.01, n)))
        low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.01, n)))
        level = 1e10 if base in ("USDC", "BTCUP", "EUR", "WBTC") else 10 ** rng.uniform(6.0, 9.5)
        qv = level * np.exp(rng.normal(0.0, 0.5, n))
        frame = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": qv / close, "quote_volume": qv},
            index=grid,
        ).iloc[first : last_row + 1]
        if i >= 2:
            gaps = rng.choice(len(frame), size=min(3, len(frame) // 50), replace=False)
            frame = frame.drop(frame.index[gaps])
        frames[f"{base}USDT"] = frame
    return frames


def synthetic_loader(seed: int, n_coins: int) -> Callable:
    def load(end, catalog_dir=None):
        end = pd.Timestamp(end)
        if end > DATA_END:
            raise HoldoutWindowError(f"synthetic loader: {end} is after the last close {DATA_END}")
        return {s: f.loc[:end] for s, f in synthetic_frames(seed, n_coins).items() if len(f.loc[:end])}

    return load


def real_loader(catalog_dir: Path) -> Callable:
    from lab.data import bold

    return partial(bold.load_bold_daily, catalog_dir=catalog_dir)


def real_snapshot(catalog_dir: Path) -> dict:
    from lab.data import bold

    snap = bold.bold_snapshot(catalog_dir=catalog_dir)
    if isinstance(snap, Mapping):
        return {"snapshot_id": snap.get("snapshot_id"), "sha256": snap.get("sha256", snap.get("hash"))}
    return {"snapshot_id": snap[0], "sha256": snap[1]}


def load_train(loader: Callable, snapshot_id: str) -> pd.DataFrame:
    """Section 3: ask for closes up to 2023-01-01 00:00 only; a later close is stop rule 3; build the panel and
    check it (stop rule 2)."""
    try:
        frames = loader(LAST_CLOSE)
    except HoldoutWindowError as exc:
        raise Stop("3", f"the loader refused: {exc}") from exc
    for sym, frame in frames.items():
        latest = frame.index.max()
        if latest > LAST_CLOSE:
            raise Stop("3", f"{sym}: a close {latest.isoformat()} after {LAST_CLOSE.isoformat()}; nothing is used")
    try:
        panel = M.make_wide_panel(frames, snapshot_id=snapshot_id)
    except ValueError as exc:
        raise Stop("2", f"the bars do not make a wide panel: {exc}") from exc
    btc = panel[(M.BTC, "close")]
    first = btc.first_valid_index()
    if first is None or btc.loc[first:].isna().any() or panel.index[-1] != LAST_CLOSE:
        raise Stop("2", "BTCUSDT must have every close from its first through 2023-01-01 (section 3)")
    return panel.loc[first:]


# ------------------------------------------------------------------------------------------- the study


def projection(sizes: Sizes, seconds: float) -> dict:
    backtests = N_FOLDS * (sizes.n_trials + 2 + 1 + 1 + 4 + 3 + sizes.n_draws)
    return {"backtests": backtests, "seconds_each": seconds, "cpu_minutes": backtests * seconds / 60.0}


def measure_timing(sizes: Sizes) -> dict:
    frames = synthetic_frames(399999, sizes.timing_coins, LAST_CLOSE)
    panel = M.make_wide_panel(frames, snapshot_id="timing")
    costs = M.coin_costs()
    t0 = time.process_time()
    for _ in range(TIMING_REPS):
        M.momentum(TIMING_PARAMS, panel, costs)
    return projection(sizes, (time.process_time() - t0) / TIMING_REPS)


def null_seed(fold: int, draw: int) -> int:
    return 10_000 * (fold + 1) + draw


def describe(run: pd.DataFrame) -> dict:
    """Section 10's reported numbers of one stitched run (kept rows only)."""
    r = run["ret"].to_numpy()
    return {
        "total_return": float(np.prod(1.0 + r) - 1.0),
        "max_drawdown": mc.max_drawdown(r),
        "turnover_per_year": float(run["turnover"].sum() * 365.0 / len(run)),
        "cost_paid": float(run["cost"].sum()),
        "fill_rows": int((run["turnover"] > 0.0).sum()),
        "mean_held": float(run["n_held"].mean()),
        "forced": int(run.attrs["forced"]),
    }


def chosen_params(folds: pd.DataFrame) -> list[dict]:
    return [
        {"lookback": int(r.p_lookback), "k": int(r.p_k), "filter": str(r.p_filter)} for r in folds.itertuples()
    ]


def study(panel: pd.DataFrame, run_dir: Path, sizes: Sizes, costs: M.CoinCosts, budget, name: str) -> dict:
    n = len(panel)
    folds = walk_forward(n, n - N_FOLDS * TEST_SIZE, TEST_SIZE, expanding=True)
    fn1 = partial(M.momentum, costs=costs)
    fn2 = partial(M.momentum, costs=costs.stressed(STRESS))
    cfg = SearchConfig(n_trials=sizes.n_trials, n_workers=1, seed=SEED)
    studies = run_dir / "studies"
    wf = walk_forward_optimize(name, fn1, SPECS, panel, folds, studies, cfg, warmup=M.WARMUP)
    chosen = chosen_params(wf["folds"])
    s = M.stitch(fn1, chosen, panel, folds)
    if not (s.index.equals(wf["oos_returns"].index) and np.array_equal(s.to_numpy(), wf["oos_returns"].to_numpy())):
        raise Stop("5", "S rerun from the chosen params is not walk_forward_optimize's oos_returns")
    runs = {"S_2x": M.stitch_frame(fn2, chosen, panel, folds)}
    steps = M.plateau_steps(chosen)
    for i, st in enumerate(steps):
        runs[f"step{i}"] = M.stitch_frame(fn1, st["folds"], panel, folds)
    bench_fn = {"B1": M.hold_fixed, "B2": M.hold_fixed, "B3": M.basket}
    for b, fn in bench_fn.items():
        runs[b] = M.stitch_frame(partial(fn, costs=costs), [B_PARAMS[b]] * N_FOLDS, panel, folds)
    runs["S"] = M.stitch_frame(fn1, chosen, panel, folds)
    draw_fn = partial(M.random_select, costs=costs)
    draws = [
        M.stitch_frame(draw_fn, [dict(p, seed=null_seed(i, j)) for i, p in enumerate(chosen)], panel, folds)
        for j in range(sizes.n_draws)
    ]
    frame = pd.DataFrame({c: r["ret"] for c, r in runs.items()})[["S", *(c for c in runs if c != "S")]]
    null_frame = pd.DataFrame({f"d{j:03d}": d["ret"] for j, d in enumerate(draws)})
    if not np.array_equal(frame["S"].to_numpy(), s.to_numpy()):
        raise Stop("5", "S's stitched frame differs from S")
    e1 = steady.e1_rank(s, null_frame.to_numpy().T)
    rep = overfitting_report(wf, studies)
    trial_sharpes = steady.report_trial_sharpes(wf["studies"], studies)
    n_strict = wf["total_trials"] + len(steps) + 1
    dsr_strict = (
        stats.deflated_sharpe_ratio(s.to_numpy(), trial_sharpes, n_trials=n_strict)["dsr"] if trial_sharpes else math.nan
    )
    regimes = steady.regime_split(s, steady.regime_table(panel[(M.BTC, "close")], s.index))
    sh = {c: stats.annualized_sharpe(frame[c].to_numpy()) for c in frame.columns}
    numbers = {
        "sharpe": sh["S"],
        "sharpe_2x": sh["S_2x"],
        "dsr_strict": dsr_strict,
        "pbo": rep["pbo_mean"],
        "plateau": [sh[f"step{i}"] for i in range(len(steps))],
        "mc_p5": rep["mc_drawdown_worst5pct"],
        "budget": budget,
        "bench": {b: sh[b] for b in bench_fn},
        "regimes_pass": regimes["pass"],
    }
    gates = M.gate_table(numbers)
    states = {st: load_trials(f"{name}_wf{i:02d}", studies)["state"].value_counts().to_dict()
              for i, st in enumerate(wf["studies"])}
    described = {c: describe(r) for c, r in runs.items()}
    described["null_mean"] = {
        k: float(np.mean([describe(d)[k] for d in draws])) for k in ("turnover_per_year", "fill_rows", "forced")
    }
    frame.to_parquet(run_dir / "oos.parquet")
    null_frame.to_parquet(run_dir / "null.parquet")
    wf["folds"].to_csv(run_dir / "folds.csv", index=False)
    return {
        "chosen": chosen,
        "trials": {"raw": wf["total_trials"], "strict": n_strict, "states": states},
        "studies": wf["studies"],
        "numbers": numbers,
        "sharpes": sh,
        "described": described,
        "correlation": {b: float(np.corrcoef(frame["S"], frame[b])[0, 1]) for b in ("B1", "B3")},
        "report": rep,
        "dsr_raw": rep["dsr_raw_count"],
        "e1_rank": {k: v for k, v in e1.items() if k != "draw_sharpes"},
        "regimes": regimes,
        "plateau_steps": steps,
        "gates": gates,
        **M.verdict(gates, e1["rank_p"]),
    }


# ------------------------------------------------------------------------------------------- main


def parse(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--time", action="store_true")
    ap.add_argument("--amendment", type=int, default=0)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--config-dir", type=Path, default=None)
    ap.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG)
    return ap.parse_args(argv)


def main(argv=None, loader: Callable | None = None) -> int:
    a = parse(argv)
    synthetic = a.synthetic is not None
    sizes = FAST if a.fast else PLAN_SIZES
    out = Path(a.out_dir) if a.out_dir is not None else DEFAULT_OUT
    runlog = runlog_path(out, synthetic)
    try:
        if a.time:  # reads no bar; --fast prices the dry run's sizes
            check_out_dir(out)
            proj = measure_timing(sizes)
            write_json(out / "time.json", proj)
            print(json.dumps(jsonable(proj)))
            return 0
        if a.fast and not synthetic:
            raise Refusal("--fast is for synthetic dry runs only")
        if synthetic:
            check_out_dir(out)
        else:
            check_real_paths(out, a.config_dir, a.catalog_dir)
        git = git_state()
        if git["dirty"] and not synthetic:
            raise Refusal("the git tree is dirty: a real run starts from a clean tree (stop rule 1)")
        if not synthetic and SNAPSHOT is None:
            raise Refusal("SNAPSHOT is not pinned: amendment D1 writes the data snapshot first (section 3)")
        check_layout(out, a.amendment, synthetic, runlog)
        snap = {"snapshot_id": "synthetic", "sha256": "synthetic"}
        if not synthetic:
            snap = real_snapshot(a.catalog_dir)
            if snap != SNAPSHOT:
                raise Refusal(f"the catalog's snapshot {snap} is not the pinned {SNAPSHOT} (stop rule 2)")
        try:
            costs = M.coin_costs(a.config_dir)
            budget = M.bold_budget(a.config_dir)
        except (OSError, ValueError) as exc:
            raise Refusal(f"config: {exc}") from exc
        try:
            proj = measure_timing(sizes)
        except Exception as exc:  # noqa: BLE001 - a timing failure refuses the start
            raise Refusal(f"the timing failed: {exc!r}") from exc
        if not synthetic and proj["cpu_minutes"] > CPU_MINUTES_MAX:
            raise Refusal(f"projection {proj['cpu_minutes']:.1f} CPU-minutes > {CPU_MINUTES_MAX} (stop rule 7)")
        hashes = file_hashes(a.config_dir)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    run_dir = out / f"run{a.amendment}"
    run_dir.mkdir(parents=True)
    data = "synthetic" if synthetic else "real"
    start = {
        "study": STUDY,
        "run": a.amendment,
        "data": data,
        "seed": a.synthetic,
        "fast": a.fast,
        "sizes": asdict(sizes),
        "utc": datetime.now(UTC).isoformat(),
        "git": git,
        "config_hash": config_hash(hashes),
        "files": hashes,
        "snapshot": snap,
        "budget": budget,
        "costs": {"major": asdict(costs.major), "minor": asdict(costs.minor)},
        "projection": proj,
        "interpretations": INTERPRETATIONS,
    }
    write_json(run_dir / "start.json", start)
    append_runlog(runlog, {"event": "start", "run": a.amendment, "data": data, "utc": start["utc"]})
    summary = {"status": "running", "start": "start.json"}
    try:
        if loader is None:
            loader = synthetic_loader(a.synthetic, sizes.coins) if synthetic else real_loader(a.catalog_dir)
        panel = load_train(loader, snap["snapshot_id"])
        summary["panel"] = {"rows": len(panel), "first": panel.index[0], "last": panel.index[-1],
                            "symbols": len(panel.columns) // len(M.FIELDS)}
        result = study(panel, run_dir, sizes, costs, budget, f"{STUDY}_r{a.amendment}")
        if file_hashes(a.config_dir) != hashes:
            raise Stop("8", "a hashed file changed during the run; its outputs stay, nothing is reported")
        summary.update(result)
        summary["status"] = "complete"
    except Stop as exc:
        summary.update(status="stopped", rule=exc.rule, message=str(exc))
        write_json(run_dir / "summary.json", summary)
        append_runlog(runlog, {"event": "stopped", "run": a.amendment, "data": data, "rule": exc.rule})
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        summary.update(status="crashed", error=repr(exc), traceback=traceback.format_exc())
        write_json(run_dir / "summary.json", summary)
        append_runlog(runlog, {"event": "crashed", "run": a.amendment, "data": data})
        raise
    write_json(run_dir / "summary.json", summary)
    append_runlog(runlog, {"event": "end", "run": a.amendment, "data": data, "verdict": summary["verdict"]})
    print(f"{summary['verdict']}: Sharpe {summary['sharpes']['S']:.3f}; failing {summary['failing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
