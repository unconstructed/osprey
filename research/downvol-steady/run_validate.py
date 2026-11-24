"""The single validate look of the downvol-steady study (PLAN.md section 13, TP 13).

SCOUTING ONLY: the reference portfolio engine (lab.runner.trend's executor via lab.runner.downvol), not
NautilusTrader (AGENTS.md hard rule 3), with PLACEHOLDER costs. Reads bars closing up to 2024-07-01 00:00 UTC (train +
validate) and never anything later. vol-steady's run_validate.py adapted: the downside-volatility rule, and E9's
validate shifts are the q-only shifts of amendment M1 (with theta's one s they equal VP's whole-schedule shifts).

    uv run python research/downvol-steady/run_validate.py                        # the look, on real data
    uv run python research/downvol-steady/run_validate.py --synthetic 7 --out-dir <scratch> --allow-dirty

Start guard: refuses a real look outside the pinned folders (results/downvol-steady, config/, data/catalog) and a dry
run inside results/downvol-steady or the repo; refuses if the RUNLOG already records a look, if ``validate/STARTED`` or
``validate/look.json`` exists, if the git tree is dirty, if FROZEN.json is missing or any hash differs from it (stop
rule 10; also every file under train/, the committed FROZEN.json copy, and FROZEN.json's own numbers against the
reported run's summary.json), or if the look is not earned (the reported look_earned: E1-E8 and P in the frozen run and
in every earlier run it is reported beside, stop rules 8 and 18). Otherwise, BEFORE loading any validate bar,
it appends its start to RUNLOG.jsonl and writes ``validate/STARTED``: a crashed look counts as the look (stop rule 9).

Consistency checks before any validate number: the first 2190 Kraken rows and the first 1963 Binance rows hash to the
train panels' hashes, and theta_final(A) and theta_final(B) re-run on the 2190 Kraken train rows reproduce their
logged trial returns bit for bit. If either fails, the look is spent and the verdict is INCONCLUSIVE.

Then, once: theta_final(A) in H0 on Kraken rows 0-2736 at 1x (t0 = row 2190, close 2023-01-02; 546 kept returns), its
N0 from its book at close t0 and its 25 guarded q-only shifts (u = 53..77) over the 78 validate check closes decide E9;
everything else is a description. The look's verdict and headline are the frozen run's own after E9, combined under
stop rule 18 with the train values of every earlier run it is reported beside (the least favourable); its own values
after E9 are recorded next to them.
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
from lab.runner import downvol as D
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner import volsteady as V


def _study_module():
    name = "downvol_steady_study"
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
    """Every start refusal; returns FROZEN.json and the checks."""
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
        raise S.Refusal(f"{frozen_path} does not exist: run freeze.py first (section 13)")
    frozen = json.loads(frozen_path.read_text())
    if (frozen["data"] == "synthetic") != synthetic:
        raise S.Refusal(f"FROZEN.json is from a {frozen['data']} train run; this look is not")
    if frozen["reported"]["look_earned"] is not True and not args.any_verdict:
        raise S.Refusal(
            f"the reported train verdict is {frozen['reported']['verdict']} (the frozen run's own: "
            f"{frozen['verdict']['label']}): no validate look (stop rules 8 and 18)"
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
    """FROZEN.json's numbers are the reported run's (INTERPRETATIONS["look_hash_check"])."""
    path = train / f"run{frozen['run']}" / "summary.json"
    if not path.is_file() or S.sha256_file(path) != frozen["summary_sha256"]:
        raise S.Refusal(f"{path} is not the summary FROZEN.json was frozen from")
    expected = S.frozen_numbers(json.loads(path.read_text())["results"])
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


def validate_window(index: pd.DatetimeIndex) -> sd.Window:
    first, end = S.VALIDATE_TEST
    return sd.fold_window(index, np.arange(first, end + 1), warmup=T.WARMUP)


def validate_steps(index: pd.DatetimeIndex, w: sd.Window, z, share, q, s: float) -> D.StepSchedule:
    """The schedule over the validate check closes whose orders fill by 2024-07-01 (INTERPRETATIONS
    ["validate_checks"]), with each check's q and s for E9's q-only shifts: a check on the last close (2024-07-01 is a
    Monday) decides nothing and is left out. ``share`` and ``q``: the run's share and q in force per row; ``s``: its
    crypto share."""
    steps = D.stitched_steps(index, [w], [z], [share], [q], [s])
    sched = steps.schedule
    if int(sched.checks[-1]) == len(index) - 1:
        sched = T.Schedule(
            sched.checks[:-1], sched.z[:-1], sched.share[:-1], sched.fold[:-1], sched.head_z, sched.head_share
        )
        steps = D.StepSchedule(sched, steps.q[:-1], steps.s[:-1])
    return steps


def evaluate(K: pd.DataFrame, w: sd.Window, params: dict, *, limits, costs) -> dict:
    """A fixed configuration on the validate block (section 13): its run from row 0, its N0 from its book at t0,
    its schedule over the validate check closes (R_0, equal to the run on the kept rows) and its guarded q-only
    shifts."""
    run = D.downvol_backtest(params, K, limits=limits, costs=costs)
    kept = S.kept_of(run, w.t0)
    share = float(params["crypto_share"])
    n0_run = T.always_in_n0(
        K, run.attrs["targets"], w.t0, share, limits=limits, costs=costs, base_states=run.attrs["z"]
    )
    if not T.same_book_at(n0_run, run, w.t0):
        raise S.Stop("stop rule 14: the validate N0 does not hold theta's book at t0 bit for bit")
    steps = validate_steps(K.index, w, run.attrs["z"], run.attrs["share"], run.attrs["q"], share)
    sched = steps.schedule
    if len(sched.checks) != S.W_VALIDATE:
        raise S.Stop(
            f"{len(sched.checks)} validate check closes; the plan counts {S.W_VALIDATE} (appendix B)"
        )
    r0 = T.run_span(K, sched, limits=limits, costs=costs)
    if not np.array_equal(r0["ret"].loc[kept.index].to_numpy(), kept.to_numpy()):
        raise S.Stop(
            "stop rule 14: the validate schedule run is not theta's run on the kept rows bit for bit"
        )
    shifts = {}
    for u in T.guarded_offsets(S.W_VALIDATE).tolist():
        res = D.run_q_shift(K, steps, limits=limits, costs=costs, u=u)
        if not T.same_book_at(res, run, w.t0):
            raise S.Stop(f"stop rule 14: the validate q-only shift u = {u} does not hold theta's book at t0")
        shifts[u] = res["ret"].loc[kept.index].to_numpy(dtype=float)
    shift_sharpes = [S.sharpe(x) for x in T.guarded(shifts, S.W_VALIDATE)]
    n0 = S.kept_of(n0_run, w.t0)
    return {
        "run": run,
        "S": kept,
        "N0": n0,
        "sharpe": S.sharpe(kept),
        "sharpe_n0": S.sharpe(n0),
        "shift_sharpes": shift_sharpes,
        "shift_median": float(np.median(shift_sharpes)),
    }


def look_reported(frozen: dict, verdict: dict, head: dict) -> dict:
    """Stop rule 18 at the look (INTERPRETATIONS["reported"]): the frozen run's own verdict and headline after E9,
    combined with the train values of the earlier runs it is reported beside, are the look's verdict and headline."""
    rep = frozen["reported"]
    own = {**frozen["own"], "verdict": verdict["label"], "headline": head["headline"]}
    combined = S.combine_reported(rep["beside"], own)
    return {
        "verdict": {
            "verdict": S.outcome_base(combined["verdict"], T.VERDICT_ORDER),
            "label": combined["verdict"],
        },
        "headline": {"headline": combined["headline"]},
        "record": {
            "verdict": combined["verdict"],
            "headline": combined["headline"],
            "own_after_e9": {key: own[key] for key in ("verdict", "headline")},
            "beside": rep["beside"],
            "trigger": rep["trigger"],
            "superseded": rep["superseded"],
            "runs": rep["runs"],
        },
    }


def look(args, g: dict, out: Path, vdir: Path) -> dict:
    frozen, config_dir = g["frozen"], g["config_dir"]
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
    costs1 = S.costs_for(config_dir)
    costs2 = costs1.stressed()
    fn1 = partial(D.downvol_backtest, limits=limits, costs=costs1)
    reproduced = reproduce(frozen, out / "train", fn1, K.iloc[: frozen["panels"][S.SOURCE]["rows"]])
    if not all(reproduced.values()):
        raise S.Stop(f"theta_final does not reproduce its logged train returns: {reproduced}")
    w = validate_window(K.index)
    rows, series = [], {}

    def record(name, kind, params, metrics, **extra):
        rows.append(
            {
                "id": name,
                "kind": kind,
                "params": json.dumps(S.jsonable(params), sort_keys=True) if params else "",
                **{
                    k: metrics.get(k, np.nan)
                    for k in ("rows", "sharpe", "total_return", "max_drawdown", "worst_day")
                },
                "extra": json.dumps(S.jsonable(extra), sort_keys=True),
                "window": "validate 2023-01-01 .. 2024-06-30 (kept closes 2023-01-03 .. 2024-07-01)",
                "config_hash": frozen["config_hash"],
                "snapshot": frozen["snapshot"]["snapshot_id"],
                "label": S.LABEL,
            }
        )

    theta = {lab: S.plain_params(v["params"]) for lab, v in frozen["theta_final"].items()}
    a = evaluate(K, w, theta["A"], limits=limits, costs=costs1)
    if len(a["S"]) != S.VALIDATE_KEPT:
        raise S.Stop(f"{len(a['S'])} kept validate rows, the plan counts {S.VALIDATE_KEPT} (section 13)")
    sharpe_train = frozen["train_sharpe"]["A"]
    e9 = T.e9_holds(a["sharpe"], sharpe_train, a["sharpe_n0"], a["shift_sharpes"])
    record("theta_A", "theta_final", theta["A"], S.series_metrics(a["S"]))
    record("N0_A", "N0", None, S.series_metrics(a["N0"]))
    for u, sh in zip(T.guarded_offsets(S.W_VALIDATE).tolist(), a["shift_sharpes"], strict=True):
        record(f"shift_{u}", "shift", None, {"sharpe": sh}, offset=u)
    series.update(theta_A=a["S"], N0_A=a["N0"])
    # descriptions only: they cannot change E9 or the verdict
    kept = a["S"].index
    covered = T.covered_days(K.index, kept)
    log = S.fixed_log(a["run"], kept)
    desc = {
        "theta_A": {"sharpe": a["sharpe"], "sharpe_n0": a["sharpe_n0"], "shift_median": a["shift_median"]}
    }
    desc["trade_frequency"] = S.frequency(log, kept, [w])
    grid = {}
    default = frozen["default"]["share"]
    for s_k in T.ALLOWED_S:
        e = evaluate(K, w, S.with_share(theta["A"], s_k), limits=limits, costs=costs1)
        grid[f"{s_k:.2f}"] = {
            "sharpe": e["sharpe"],
            "sharpe_n0": e["sharpe_n0"],
            "shift_median": e["shift_median"],
            "e9_rule": T.e9_holds(e["sharpe"], sharpe_train, e["sharpe_n0"], e["shift_sharpes"]),
            "default": s_k == default,
        }
        record(f"grid_{s_k:.2f}", "grid", S.with_share(theta["A"], s_k), S.series_metrics(e["S"]))
    desc["grid"] = grid
    b = S.kept_of(D.downvol_backtest(theta["B"], K, limits=limits, costs=costs1), w.t0)
    record("theta_B", "theta_final", theta["B"], S.series_metrics(b))
    run2 = D.downvol_backtest(theta["A"], K, limits=limits, costs=costs2)
    if run2.attrs["order_hash"] != a["run"].attrs["order_hash"]:
        raise S.Stop("stop rule 13: theta_final(A) orders differently at 2x on the validate panel")
    s2 = S.kept_of(run2, w.t0)
    record("theta_A_2x", "theta_final_2x", theta["A"], S.series_metrics(s2))
    b1 = S.kept_of(sd.buy_and_hold_b1(K, w, costs1), w.t0)
    b2 = S.kept_of(sd.fifty_fifty_b2(K, w, costs1), w.t0)
    x_run, x_info = T.exposure_x(K, a["run"], w.t0, limits=limits, costs=costs1)
    x = S.kept_of(x_run, w.t0)
    bn_run = D.downvol_backtest(theta["A"], T.h0_slice(Bn, w, like=K), limits=limits, costs=costs1)
    bn = S.kept_of(bn_run, w.t0)
    if not bn.index.equals(kept):
        raise sd.SliceMismatchError("the Binance validate kept rows differ from Kraken's")
    for name, r in (("B1", b1), ("B2", b2), ("X_A", x), ("theta_A_binance", bn)):
        record(name, name, None, S.series_metrics(r))
        series[name] = r
    table = sd.regime_table(K[("BTC", "close")], kept)
    split = sd.regime_split(a["S"], table, benchmark=a["N0"])
    desc.update(
        theta_B=S.series_metrics(b),
        costs_2x=S.series_metrics(s2),
        B1=S.series_metrics(b1),
        B2=S.series_metrics(b2),
        X={**S.series_metrics(x), "info": x_info},
        binance_A=S.series_metrics(bn),
        regimes={"split": split, "g8_excess_rule": T.g8_excess_pass(split)},
        monte_carlo={"g6_statistic": S.g6_of(a["S"]), "max_drawdown": S.drawdown_of(a["S"])},
        R1=T.r1_check(log, kept, covered),
        risk=S.r2_r5(
            limits, S.plain(a["run"].loc[kept]), log, a["run"].attrs["q"][a["run"].index.get_indexer(kept)]
        ),
    )
    pd.DataFrame(series).to_parquet(vdir / "series.parquet")
    criteria = {**frozen["criteria"], "E9": e9}
    verdict = V.verdict(criteria, changes=frozen["p_changes"])
    points = {(p["item"], p["point"]): p["value"] for p in frozen["points"]}
    head = V.headline(verdict, points)
    reported = look_reported(frozen, verdict, head)
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
            "E9": {
                "holds": e9,
                "sharpe": a["sharpe"],
                "train_sharpe_A": sharpe_train,
                "sharpe_n0": a["sharpe_n0"],
                "shift_sharpes": a["shift_sharpes"],
                "shift_median": a["shift_median"],
            },
            "criteria": criteria,
            "verdict": reported["verdict"],
            "headline": reported["headline"],
            "own": {"verdict": verdict, "headline": head},
            "reported": reported["record"],
            "descriptions": desc,
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
                "verdict": {"verdict": T.INCONCLUSIVE, "label": T.INCONCLUSIVE, "look_earned": False},
                "headline": {"headline": T.INCONCLUSIVE, "failing": []},
                "note": "the look is spent (section 13, stop rule 9)",
            },
        )
        print(f"STOP: {exc}. The look is spent; the verdict is INCONCLUSIVE", file=sys.stderr)
        return 3
    except Exception as exc:  # a crash: the look is spent too (stop rule 9), and the error is raised
        S.write_json(
            vdir / "look.json",
            {
                **base,
                "label": S.LABEL,
                "crashed": f"{type(exc).__name__}: {exc}",
                "verdict": {"verdict": T.INCONCLUSIVE, "label": T.INCONCLUSIVE, "look_earned": False},
                "headline": {"headline": T.INCONCLUSIVE, "failing": []},
                "note": "the look crashed and is spent (section 13, stop rule 9)",
            },
        )
        raise
    S.write_json(vdir / "look.json", {**base, **res["look"], "runtime_s": time.time() - t})
    tracked = S.tracked_dir(out, synthetic)
    tracked.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(res["rows"]).to_csv(tracked / "validate.csv", index=False)
    lk = res["look"]
    print(
        f"validate look done in {time.time() - t:.1f}s: E9 {lk['E9']['holds']} (Sharpe {lk['E9']['sharpe']:.3f}); "
        f"verdict {lk['verdict']['label']}; headline {lk['headline']['headline']}",
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
