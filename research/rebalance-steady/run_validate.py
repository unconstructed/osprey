"""The single validate look of the rebalance-steady study (PLAN.md section 11; look #1 of section 15).

SCOUTING ONLY: the reference rebalancer, not NautilusTrader (AGENTS.md hard rule 3), with PLACEHOLDER costs. Reads
bars closing up to 2024-07-01 00:00 UTC (train + validate) and never anything later.

    uv run python research/rebalance-steady/run_validate.py                        # the look, on real data
    uv run python research/rebalance-steady/run_validate.py --synthetic 7 --out-dir <scratch> --allow-dirty

Start guard: refuses a real look outside the pinned folders (results/rebalance-steady, config/, data/catalog) and a
dry run inside results/rebalance-steady or the repo; refuses if the RUNLOG already records a look, if
``validate/STARTED`` or ``validate/look.json`` exists, if the git tree is dirty, if FROZEN.json is missing or any
hash differs from it (the rule of freeze.py, stop rule 10; also every file under train/, the committed FROZEN.json
copy, and FROZEN.json's own numbers against the reported run's summary.json), or if the train verdict does not
call for the look. Otherwise, BEFORE loading any validate bar, it appends its start to RUNLOG.jsonl and writes
``validate/STARTED``: a crashed look counts as the look (stop rule 9).

Consistency checks before any validate number: the first 2190 Kraken rows and the first 1963 Binance rows hash to
the train panels' hashes, and theta_final(A) and theta_final(B) re-run on the 2190 Kraken rows reproduce their
logged trial returns bit for bit. If either fails, the look is spent and the verdict is INCONCLUSIVE.

Then, once: theta_final(A) on Kraken validate at 1x with B3 (seeds 10*j, k = its own validate fills) and B4 from
its book at close 2023-01-01 decide E6; everything else is a description.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.external import HoldoutWindowError
from lab.runner import steady as sd
from lab.runner.reference import Costs
from lab.validation import montecarlo as mc


def _study_module():
    name = "rebalance_steady_study"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("study.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


S = _study_module()


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=str(S.DEFAULT_OUT))
    ap.add_argument("--catalog-dir", default=str(S.DEFAULT_CATALOG))
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED", help="dry run on synthetic bars")
    ap.add_argument("--allow-dirty", action="store_true", help="dry runs only: run on a dirty git tree")
    ap.add_argument(
        "--any-verdict", action="store_true", help="dry runs only: look whatever the train verdict"
    )
    return ap.parse_args(argv)


def guard(args) -> dict:
    """Every start refusal; returns FROZEN.json."""
    synthetic = args.synthetic is not None
    if not synthetic and (args.allow_dirty or args.any_verdict):
        raise S.Refusal("--allow-dirty and --any-verdict are for synthetic dry runs only")
    out = Path(args.out_dir)
    config_dir = Path(args.config_dir) if args.config_dir else None
    S.check_paths(out, config_dir, Path(args.catalog_dir), synthetic)
    data = "synthetic" if synthetic else "real"
    runlog = S.runlog_path(out, synthetic)
    looks = [
        x for x in S.runlog_entries(runlog) if x.get("script") == "run_validate.py" and x.get("data") == data
    ]
    if looks:
        raise S.Refusal(
            f"{runlog} records a {data} look started {looks[0].get('utc')}: a second look needs a new "
            "pre-registration, and the verdict becomes INCONCLUSIVE (stop rule 9)"
        )
    vdir = out / "validate"
    for name in ("STARTED", "look.json"):
        if (vdir / name).exists():
            raise S.Refusal(
                f"{vdir / name} exists: the validate window was looked at. A second look needs a new "
                "pre-registration, and the verdict becomes INCONCLUSIVE (stop rule 9)"
            )
    frozen_path = out / "FROZEN.json"
    if not frozen_path.is_file():
        raise S.Refusal(f"{frozen_path} does not exist: run freeze.py first (section 11)")
    frozen = json.loads(frozen_path.read_text())
    if (frozen["data"] == "synthetic") != synthetic:
        raise S.Refusal(f"FROZEN.json is from a {frozen['data']} train run; this look is not")
    if not frozen["train_verdict"]["look_due"] and not args.any_verdict:
        raise S.Refusal(
            f"the train verdict is {frozen['train_verdict']['verdict']}: no validate look (stop rule 8)"
        )
    git = S.git_state()
    if git["dirty"] and not (synthetic and args.allow_dirty):
        raise S.Refusal(f"the git tree is dirty: commit first. Changes: {git['changes'][:10]}")
    check = S.compare_hashes(
        frozen["file_hashes"],
        frozen["config_hash"],
        S.file_hashes(config_dir),
        frozen["risk_limits_train_start"],
        config_dir,
    )
    if not check["ok"]:
        raise S.Refusal(f"a hash differs from FROZEN.json (stop rule 10): {check['differs']}")
    tree = S.tree_hashes(out / "train")
    if tree != frozen["train_outputs_sha256"]:
        changed = sorted(set(tree.items()) ^ set(frozen["train_outputs_sha256"].items()))
        raise S.Refusal(f"files under train/ changed since the freeze: {[p for p, _ in changed][:10]}")
    copy = S.tracked_dir(out, synthetic) / "FROZEN.json"
    if not copy.is_file() or copy.read_bytes() != frozen_path.read_bytes():
        raise S.Refusal(
            f"{copy} is not a byte-identical copy of {frozen_path} (commit the copy before the look)"
        )
    check_frozen_content(frozen, out / "train")
    snapshot = S.read_snapshot(Path(args.catalog_dir), synthetic)
    if snapshot != frozen["snapshot"]:
        raise S.Refusal(f"the snapshot {snapshot} is not the frozen one {frozen['snapshot']}")
    return {"frozen": frozen, "git": git, "check": check, "config_dir": config_dir}


def check_frozen_content(frozen: dict, train: Path) -> None:
    """FROZEN.json's numbers are the reported run's (INTERPRETATIONS["look_hash_check"]): its summary.json has the
    SHA-256 FROZEN.json recorded, and theta_final, the fold params, E, the train verdict, the gates and the train
    Sharpes in FROZEN.json equal that summary's."""
    path = train / f"run{frozen['run']}" / "summary.json"
    if not path.is_file() or S.sha256_file(path) != frozen["summary_sha256"]:
        raise S.Refusal(f"{path} is not the summary FROZEN.json was frozen from")
    results = json.loads(path.read_text())["results"]
    expected = {
        "theta_final": results["theta_final"],
        "fold_params": {lab: s["params"] for lab, s in results["seeds"].items()},
        "E": results["E"],
        "train_verdict": results["train_verdict"],
        "gates": {lab: s["gates"] for lab, s in results["seeds"].items()},
        "train_sharpe": {lab: s["sharpe"] for lab, s in results["seeds"].items()},
    }
    differ = sorted(key for key, value in expected.items() if frozen.get(key) != value)
    if differ:
        raise S.Refusal(f"FROZEN.json's {differ} are not those of {path}")


def reproduce(frozen: dict, train: Path, fn1, kraken_train: pd.DataFrame) -> dict:
    """theta_final(A) and (B) re-run on the train rows equal their logged trial returns bit for bit."""
    out = {}
    for label, theta in frozen["theta_final"].items():
        res = fn1(theta["params"], kraken_train)
        logged = pd.read_parquet(
            train / theta["study"] / "returns" / f"trial_{theta['trial_number']:06d}.parquet"
        )
        col = logged.iloc[:, 0]
        out[label] = bool(
            col.index.equals(res.index) and np.array_equal(col.to_numpy(), res["ret"].to_numpy())
        )
    return out


def look(args, g: dict, out: Path, vdir: Path) -> dict:
    frozen, config_dir = g["frozen"], g["config_dir"]
    settings = S.Settings(**frozen["settings"])
    loader = S.synthetic_bar_loader(args.synthetic) if args.synthetic is not None else None
    panels = {}
    for source in (S.SOURCE, S.ROBUSTNESS):
        panel = S.load_study_panel(
            source,
            S.VALIDATE_LAST_CLOSE,
            catalog_dir=Path(args.catalog_dir),
            config_dir=config_dir,
            loader=loader,
        )
        if len(panel) != S.ROWS["validate"][source]:
            raise S.Stop(f"{source}: {len(panel)} rows, the plan counts {S.ROWS['validate'][source]}")
        panels[source] = panel
    K, Bn = panels[S.SOURCE], panels[S.ROBUSTNESS]
    consistency = {
        src: S.panel_record(panels[src].iloc[: frozen["panels"][src]["rows"]])["hash"]
        == frozen["panels"][src]["hash"]
        for src in panels
    }
    if not all(consistency.values()):
        raise S.Stop(
            f"the train rows of the validate panels do not hash to the frozen train panels: {consistency}"
        )
    limits = sd.steady_limits(config_dir)
    costs1 = Costs.from_yaml(None if config_dir is None else config_dir / "costs.yaml")
    costs2 = costs1.stressed()
    fn1 = partial(sd.steady_backtest, limits=limits, costs=costs1)
    fn2 = partial(sd.steady_backtest, limits=limits, costs=costs2)
    reproduced = reproduce(frozen, out / "train", fn1, K.iloc[: frozen["panels"][S.SOURCE]["rows"]])
    if not all(reproduced.values()):
        raise S.Stop(f"theta_final does not reproduce its logged train returns: {reproduced}")
    first, end = S.VALIDATE_TEST
    w = sd.fold_window(K.index, np.arange(first, end + 1))
    print(f"validate: H120 from {w.first_h120}, H1 from {w.first_h1}, t0 {w.t0}, last {w.last}", flush=True)

    rows, series, numbers = [], {}, {}

    def record(name, kind, seed, source, cost_x, params, metrics, **extra):
        rows.append(
            {
                "id": name,
                "kind": kind,
                "seed": seed,
                "source": source,
                "cost_x": cost_x,
                "params": json.dumps(S.jsonable(params), sort_keys=True) if params else "",
                **{
                    k: metrics.get(k, np.nan)
                    for k in (
                        "rows",
                        "sharpe",
                        "total_return",
                        "max_drawdown",
                        "worst_day",
                        "fills",
                        "turnover",
                        "cost",
                        "cost_usd",
                    )
                },
                **extra,
                "window": "validate 2023-01-01 .. 2024-06-30 (kept closes 2023-01-03 .. 2024-07-01)",
                "config_hash": frozen["config_hash"],
                "snapshot": frozen["snapshot"]["snapshot_id"],
                "label": S.LABEL,
            }
        )

    def evaluate(label: str, panel: pd.DataFrame, source: str, like=None) -> dict:
        theta = frozen["theta_final"][label]["params"]
        res = sd.run_h120(fn1, theta, panel, w, like=like)
        kept = sd.kept_returns(res, w.t0)
        k = sd.kept_fills(res, w.t0)
        book = sd.book_value(res, w, costs1)
        b3 = sd.random_b3(panel, w, theta, k, costs1, book, 0, n_draws=settings.b3_draws, like=like)
        if not (b3["fills"] == k).all():
            raise S.Stop(f"{label} {source}: a B3 draw's kept fills differ from k = {k}")
        b4 = sd.kept_returns(sd.static_b4(panel, w, theta, costs1, book, like=like), w.t0)
        rank = sd.e1_rank(kept, b3["returns"])
        tag = f"{label}" if source == S.SOURCE else f"{label}_binance"
        record(f"S_{tag}", "S", label, source, 1, theta, S.result_metrics(res, w.t0), k=k, book_usd=book)
        record(
            f"B3_{tag}",
            "B3",
            label,
            source,
            1,
            theta,
            {"rows": len(kept), "fills": k},
            b3_sharpe_p5=rank["p5"],
            b3_sharpe_p50=rank["p50"],
            b3_sharpe_p95=rank["p95"],
            s_rank_p=rank["rank_p"],
        )
        record(f"B4_{tag}", "B4", label, source, 1, theta, S.series_metrics(b4), book_usd=book)
        series[f"S_{tag}"], series[f"B4_{tag}"] = kept, b4
        return {
            "theta": theta,
            "S": kept,
            "B4": b4,
            "k": k,
            "book": book,
            "rank": rank,
            "res": res,
            "sharpe": S.sharpe(kept),
            "sharpe_b4": S.sharpe(b4),
        }

    a = evaluate("A", K, S.SOURCE)
    if len(a["S"]) != S.VALIDATE_KEPT:
        raise S.Stop(f"{len(a['S'])} kept validate rows, the plan counts {S.VALIDATE_KEPT} (section 11)")
    sharpe_train = frozen["train_sharpe"]["A"]
    e6_parts = S.e6_parts(a["sharpe"], sharpe_train, a["sharpe_b4"], a["rank"]["p50"])
    e6 = e6_parts["holds"]
    # descriptions only: they cannot change E6 or the verdict
    b = evaluate("B", K, S.SOURCE)
    bn = evaluate("A", Bn, S.ROBUSTNESS, like=K)
    if not bn["S"].index.equals(a["S"].index):
        raise sd.SliceMismatchError("the Binance validate kept rows differ from Kraken's")
    for label in ("A", "B"):
        theta = frozen["theta_final"][label]["params"]
        res2 = sd.run_h120(fn2, theta, K, w)
        record(f"S_2x_{label}", "S_2x", label, S.SOURCE, 2, theta, S.result_metrics(res2, w.t0))
        res5 = sd.limit_only_b5(K, w, theta, limits, costs1)
        record(f"B5_{label}", "B5", label, S.SOURCE, 1, theta, S.result_metrics(res5, w.t0))
        numbers[f"sharpe_2x_{label}"] = S.sharpe(sd.kept_returns(res2, w.t0))
    b1 = sd.kept_returns(sd.buy_and_hold_b1(K, w, costs1), w.t0)
    b2 = sd.kept_returns(sd.fifty_fifty_b2(K, w, costs1), w.t0)
    record("B1", "B1", "", S.SOURCE, 1, None, S.series_metrics(b1))
    record("B2", "B2", "", S.SOURCE, 1, None, S.series_metrics(b2))
    table = sd.regime_table(K[("BTC", "close")], a["S"].index)
    regimes = sd.regime_split(a["S"], table, benchmark=a["B4"])
    dd = mc.block_bootstrap_drawdowns(
        a["S"].to_numpy(), mean_block=sd.MEAN_BLOCK, n_sims=settings.mc_sims, seed=0
    )
    pd.DataFrame({**series, "B1": b1, "B2": b2}).to_parquet(vdir / "series.parquet")
    e = {**frozen["E"], "E6": e6}
    verdict = S.final_verdict(e)
    return {
        "rows": rows,
        "look": {
            "label": S.LABEL,
            "window": "validate, single look",
            "last_close_read": S.VALIDATE_LAST_CLOSE.isoformat(),
            "data": frozen["data"],
            "config_hash": frozen["config_hash"],
            "snapshot": frozen["snapshot"],
            "consistency": {"panel_hashes": consistency, "theta_final_reproduced": reproduced},
            "window_closes": {k: v.isoformat() for k, v in w._asdict().items()},
            "kept_rows": len(a["S"]),
            "E6": {
                **e6_parts,
                "sharpe": a["sharpe"],
                "train_sharpe_A": sharpe_train,
                "sharpe_b4": a["sharpe_b4"],
                "b3_sharpe_p50": a["rank"]["p50"],
                "k": a["k"],
                "book_usd": a["book"],
                "b3_draws": settings.b3_draws,
            },
            "E": e,
            "verdict": verdict,
            "headline": S.headline(verdict, frozen["gates"]["A"]),
            "gates_train_A": frozen["gates"]["A"],
            "descriptions": {
                "theta_final_B": {
                    "sharpe": b["sharpe"],
                    "sharpe_b4": b["sharpe_b4"],
                    "b3": {k: b["rank"][k] for k in ("p5", "p50", "p95", "rank_p")},
                    "k": b["k"],
                },
                "binance_A": {
                    "sharpe": bn["sharpe"],
                    "sharpe_b4": bn["sharpe_b4"],
                    "b3": {k: bn["rank"][k] for k in ("p5", "p50", "p95", "rank_p")},
                    "k": bn["k"],
                },
                "costs_2x": {k: v for k, v in numbers.items()},
                "B1": S.series_metrics(b1),
                "B2": S.series_metrics(b2),
                "regimes": {
                    "split": regimes,
                    "months": table.groupby("month")
                    .first()[["month_ret", "regime"]]
                    .reset_index()
                    .to_dict(orient="records"),
                },
                "monte_carlo": {
                    "max_drawdown": S.series_metrics(a["S"])["max_drawdown"],
                    **mc.percentiles(dd, (5, 50)),
                    "sims": settings.mc_sims,
                },
            },
        },
    }


def run(args) -> int:
    g = guard(args)
    out = Path(args.out_dir)
    vdir = out / "validate"
    synthetic = args.synthetic is not None
    started = S.utc_now()
    S.append_runlog(
        S.runlog_path(out, synthetic),
        {
            "utc": started,
            "script": "run_validate.py",
            "run": "validate",
            "commit": g["git"]["commit"],
            "dirty": g["git"]["dirty"],
            "config_hash": g["frozen"]["config_hash"],
            "snapshot_id": g["frozen"]["snapshot"]["snapshot_id"],
            "data": g["frozen"]["data"],
            "out_dir": str(out),
        },
    )
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "STARTED").write_text(started + "\n")  # the look is taken from here on, even if it crashes
    t = time.time()
    base = {"started_utc": started, "git": g["git"], "hash_check": g["check"]}
    try:
        res = look(args, g, out, vdir)
    except (HoldoutWindowError, sd.SliceMismatchError, S.Stop) as exc:
        S.write_json(
            vdir / "look.json",
            {
                **base,
                "label": S.LABEL,
                "stopped": f"{type(exc).__name__}: {exc}",
                "verdict": "INCONCLUSIVE",
                "headline": "INCONCLUSIVE",
                "note": "the look is spent (section 11, stop rule 9)",
            },
        )
        print(f"STOP: {exc}. The look is spent; the verdict is INCONCLUSIVE", file=sys.stderr)
        return 3
    S.write_json(vdir / "look.json", {**base, **res["look"], "runtime_s": time.time() - t})
    tracked = S.tracked_dir(out, synthetic)
    tracked.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(res["rows"]).to_csv(tracked / "validate.csv", index=False)
    lk = res["look"]
    print(
        f"validate look done in {time.time() - t:.1f}s: E6 {lk['E6']['holds']} (Sharpe {lk['E6']['sharpe']:.3f}); "
        f"verdict {lk['verdict']}; headline {lk['headline']}",
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
