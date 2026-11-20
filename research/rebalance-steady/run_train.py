"""Train phase of the rebalance-steady study: searches, comparators, gates, criteria (PLAN.md sections 7-10, 12-13).

SCOUTING ONLY: the reference rebalancer, not NautilusTrader (AGENTS.md hard rule 3), with PLACEHOLDER costs. Reads
only bars closing up to 2023-01-01 00:00 UTC (the last train close); never the validate or test windows.

    uv run python research/rebalance-steady/run_train.py                    # run 0 on real data
    uv run python research/rebalance-steady/run_train.py --amendment 1      # amendment run 1 (stop rule 7)
    uv run python research/rebalance-steady/run_train.py --synthetic 7 --fast --out-dir <scratch>   # dry run

Start guards (all before anything is loaded): a real run uses the pinned folders only (``--out-dir``
results/rebalance-steady, ``--config-dir`` unset, ``--catalog-dir`` data/catalog) and a dry run never writes into
results/rebalance-steady or the repo; run 0 refuses if ``<out>/train/`` exists; ``--amendment k`` refuses unless
1 <= k <= 2, ``train/run<k-1>/summary.json`` exists, every earlier run has the same data and ``--fast`` setting,
neither ``train/run<k>/`` nor a study named with ``_a<k>_`` exists and (real data) PLAN.md holds the row
``- **Amendment run k``; the RUNLOG must not already hold this run number; a dirty git tree is refused (dry runs
may pass ``--allow-dirty``); the box corners must keep the headroom from the Steady limits as read.
Then, before any bar is read: one RUNLOG line and ``train/run<k>/summary.json`` with the start fields (git state,
config hash, every frozen file's SHA-256, snapshot, the Steady limits and the G6 budget as read, the run number).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.external import HoldoutWindowError
from lab.runner import steady as sd
from lab.runner.reference import Costs
from lab.search.report import overfitting_report
from lab.search.stability import stable_region
from lab.search.study import load_trial_returns, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward


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
    ap.add_argument(
        "--out-dir", default=str(S.DEFAULT_OUT), help="results folder (default results/rebalance-steady)"
    )
    ap.add_argument("--catalog-dir", default=str(S.DEFAULT_CATALOG))
    ap.add_argument(
        "--config-dir", default=None, help="folder with costs.yaml, splits.yaml, risk_levels.yaml"
    )
    ap.add_argument("--amendment", type=int, default=None, metavar="K", help="amendment run K (1 or 2)")
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED", help="dry run on synthetic bars")
    ap.add_argument("--fast", action="store_true", help="dry runs only: small trial and simulation counts")
    ap.add_argument("--allow-dirty", action="store_true", help="dry runs only: run on a dirty git tree")
    return ap.parse_args(argv)


def check_layout(train: Path, k: int) -> None:
    """Stop rule 7's start refusals for run ``k`` (0 = run 0)."""
    if k == 0:
        if train.exists():
            raise S.Refusal(
                f"{train} exists: run 0 runs once (stop rule 7). A rerun after a bug or a crash is --amendment k"
            )
        return
    if not 1 <= k <= S.MAX_AMENDMENTS:
        raise S.Refusal(
            f"--amendment {k}: amendment runs are numbered 1..{S.MAX_AMENDMENTS} (run 0 has no --amendment). "
            "If a third rerun would be needed, stop: the verdict is INCONCLUSIVE (stop rule 7)"
        )
    if not (train / f"run{k - 1}" / "summary.json").is_file():
        raise S.Refusal(f"--amendment {k}: {train / f'run{k - 1}' / 'summary.json'} does not exist")
    if (train / f"run{k}").exists():
        raise S.Refusal(f"--amendment {k}: {train / f'run{k}'} exists (a run is never resumed: stop rule 6)")
    clash = [p.name for p in train.iterdir() if f"_a{k}_" in p.name]
    if clash:
        raise S.Refusal(f"--amendment {k}: studies of amendment run {k} exist: {clash}")


def check_earlier_runs(train: Path, k: int, data: str, fast: bool) -> None:
    """Run ``k`` continues runs 0..k-1 only when they are the same kind of run (INTERPRETATIONS
    ["same_kind_of_run"]): a real amendment over a synthetic run 0, or a ``--fast`` one over a full one, is
    refused."""
    for j in range(k):
        path = train / f"run{j}" / "summary.json"
        try:
            start = json.loads(path.read_text())["start"]
            seen = (start["data"], bool(start["fast"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise S.Refusal(
                f"--amendment {k}: cannot read run {j}'s start record in {path}: {exc!r}"
            ) from exc
        if seen != (data, fast):
            raise S.Refusal(
                f"--amendment {k}: run {j} was a {seen[0]} run (fast {seen[1]}); this one is {data} (fast {fast}). "
                "An amendment run continues the same study"
            )


def check_runlog(path: Path, k: int, data: str) -> None:
    """INTERPRETATIONS["runlog_guard"]: the RUNLOG must not hold run ``k`` of this data already."""
    for line in S.runlog_entries(path):
        if line.get("script") == "run_train.py" and line.get("run") == k and line.get("data") == data:
            raise S.Refusal(
                f"{path} already records {data} run {k} (started {line.get('utc')}): a deleted run is not rerun "
                "under its number (stop rules 6-7)"
            )


def g6_budget(train: Path, k: int, limits: dict) -> dict:
    """G6's budget: run 0's train-start reading for the whole study (INTERPRETATIONS["g6_budget"])."""
    if k == 0:
        source = limits
    else:
        path = train / "run0" / "summary.json"
        try:
            source = json.loads(path.read_text())["start"]["risk_limits"]
        except (OSError, ValueError, KeyError) as exc:
            raise S.Refusal(f"G6 needs run 0's train-start reading: {path}: {exc}") from exc
    return {
        "source_run": 0,
        "max_drawdown_budget": source["max_drawdown_budget"],
        "max_drawdown_budget_pct": source["max_drawdown_budget_pct"],
        "sha256": source["sha256"],
    }


def costs_path(config_dir: Path | None) -> Path | None:
    return None if config_dir is None else Path(config_dir) / "costs.yaml"


class Evaluations:
    """Every run that is not a search trial (section 12): one row each."""

    def __init__(self, run: int):
        self.run = run
        self.rows: list[dict] = []

    def add(self, kind, seed, fold, source, cost_x, params, metrics: dict, **extra) -> None:
        self.rows.append(
            {
                "run": self.run,
                "kind": kind,
                "seed": seed,
                "fold": str(fold),
                "source": source,
                "cost_x": cost_x,
                "params": json.dumps(S.jsonable(params), sort_keys=True) if params is not None else "",
                **{
                    k: metrics.get(k, np.nan)
                    for k in ("rows", "sharpe", "total_return", "max_drawdown", "worst_day")
                },
                **{k: metrics.get(k, np.nan) for k in ("fills", "turnover", "cost", "cost_usd")},
                "extra": json.dumps(S.jsonable(extra), sort_keys=True),
                "label": S.LABEL,
            }
        )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def neighbourhood(trials: pd.DataFrame, chosen: dict) -> dict:
    """The stable region's 10 neighbours (ranges and scores) and the raw best trial (section 7)."""
    hood = sd.stable_neighbours(trials, sd.SPECS, k=S.STABLE_K)
    pick = stable_region(trials, sd.SPECS, k=S.STABLE_K)
    if S.plain_params(pick["params"]) != chosen:
        raise S.Stop("the stable region recomputed here is not the one walk_forward_optimize traded")
    nb = hood["neighbours"]
    return {
        "trial_number": hood["trial_number"],
        "neighbourhood_score": hood["neighbourhood_score"],
        "ranges": {
            n: [float(nb[f"params_{n}"].min()), float(nb[f"params_{n}"].max())] for n in sd.PARAM_NAMES
        },
        "neighbours": S.jsonable(nb.to_dict(orient="records")),
        "raw_best_params": S.plain_params(pick["raw_best_params"]),
        "raw_best_score": pick["raw_best_score"],
    }


def derived(params: dict) -> dict:
    w_btc, w_eth = sd.targets(params)
    return {"w_btc": w_btc, "w_eth": w_eth, "band": params["band_rel"] * params["coin_share"]}


def plain(x):
    """A copy without the runner's attrs (arrays and frames in attrs break ``pd.concat``)."""
    out = x.copy()
    out.attrs = {}
    return out


def kept_trade_periods(res: pd.DataFrame, t0: pd.Timestamp) -> np.ndarray:
    """The ``trade_returns`` entries whose fill row is a kept row (section 10)."""
    tr = np.asarray(res.attrs["trade_returns"], dtype=float)
    fill_rows = np.flatnonzero(res["turnover"].to_numpy() > 0)
    if len(tr) != len(fill_rows):
        raise S.Stop("trade_returns does not have one entry per fill row")
    return tr[res.index[fill_rows] > t0]


def run_comparators(
    ctx: dict,
    panel: pd.DataFrame,
    params: list[dict],
    label: str,
    source: str,
    like: pd.DataFrame | None,
    ev: Evaluations,
    settings,
) -> dict:
    """S and its nulls on one panel for one seed's per-fold params: H120 S, k_i, V, B3, B4 (and on the primary
    panel S at 2x, B4 at 2x, B1, B2, B5)."""
    windows, limits = ctx["windows"], ctx["limits"]
    costs1, costs2, fn1, fn2 = ctx["costs1"], ctx["costs2"], ctx["fn1"], ctx["fn2"]
    primary = like is None
    parts: dict[str, list] = {
        k: [] for k in ("S", "S2", "B1", "B2", "B4", "B4x2", "B5", "turnover", "trades")
    }
    b3_mats, b3_fills, fold_rows, weights = [], [], [], []
    fold_metrics: dict[str, list] = {k: [] for k in ("S", "S2", "B1", "B2", "B4", "B5")}
    for i, (w, p) in enumerate(zip(windows, params, strict=True)):
        res = sd.run_h120(fn1, p, panel, w, like=like)
        kept = sd.kept_returns(res, w.t0)
        if primary:
            wf_piece = ctx["wf"][label]["oos_returns"].loc[kept.index]
            if not (
                kept.index.equals(wf_piece.index) and np.array_equal(kept.to_numpy(), wf_piece.to_numpy())
            ):
                raise S.Stop(
                    f"seed {label} fold {i}: H120 does not reproduce walk_forward_optimize's returns"
                )
            if sd.kept_fills(res, w.t0) != int(ctx["wf"][label]["folds"].iloc[i]["oos_trades"]):
                raise S.Stop(
                    f"seed {label} fold {i}: kept fills differ from walk_forward_optimize's oos_trades"
                )
        elif not kept.index.equals(ctx["K"].loc[w.t0 : w.last].index[1:]):
            raise sd.SliceMismatchError(f"fold {i}: {source} kept rows differ from Kraken's")
        k_i = sd.kept_fills(res, w.t0)
        book = sd.book_value(res, w, costs1)
        b3 = sd.random_b3(panel, w, p, k_i, costs1, book, i, n_draws=settings.b3_draws, like=like)
        if not b3["index"].equals(kept.index):
            raise S.Stop(f"fold {i}: B3's kept rows differ from S's")
        b4res = sd.static_b4(panel, w, p, costs1, book, like=like)
        b4 = sd.kept_returns(b4res, w.t0)
        m = S.result_metrics(res, w.t0)
        fold_metrics["S"].append(m)
        fold_metrics["B4"].append(S.result_metrics(b4res, w.t0))
        row = {
            "fold": i,
            "params": p,
            **derived(p),
            "k": k_i,
            "book_usd": book,
            "metrics": m,
            "b3_fills_mean": float(b3["fills"].mean()),
        }
        ev.add("S", label, i, source, 1, p, m, k=k_i, book_usd=book)
        ev.add("B4", label, i, source, 1, p, S.series_metrics(b4), book_usd=book)
        parts["S"].append(kept)
        parts["B4"].append(b4)
        parts["turnover"].append(plain(res["turnover"].loc[w.t0 :].iloc[1:]))
        parts["trades"].append(kept_trade_periods(res, w.t0))
        b3_mats.append(b3["returns"])
        b3_fills.append(b3["fills"])
        if not (b3["fills"] == k_i).all():
            raise S.Stop(f"seed {label} {source} fold {i}: a B3 draw's kept fills differ from k_i = {k_i}")
        if primary:
            res2 = sd.run_h120(fn2, p, panel, w)
            kept2 = sd.kept_returns(res2, w.t0)
            book2 = sd.book_value(res2, w, costs2)
            b4x2 = sd.kept_returns(sd.static_b4(panel, w, p, costs2, book2), w.t0)
            if not np.array_equal(b4x2.to_numpy(), b4.to_numpy()):
                raise S.Stop(f"seed {label} fold {i}: B4 at 2x differs from B4 at 1x")
            b1res, b2res = sd.buy_and_hold_b1(panel, w, costs1), sd.fifty_fifty_b2(panel, w, costs1)
            b1, b2 = sd.kept_returns(b1res, w.t0), sd.kept_returns(b2res, w.t0)
            b5res = sd.limit_only_b5(panel, w, p, limits, costs1)
            b5 = sd.kept_returns(b5res, w.t0)
            m2, m5 = S.result_metrics(res2, w.t0), S.result_metrics(b5res, w.t0)
            m1, mb2 = S.result_metrics(b1res, w.t0), S.result_metrics(b2res, w.t0)
            for name, metrics in (("S2", m2), ("B1", m1), ("B2", mb2), ("B5", m5)):
                fold_metrics[name].append(metrics)
            ev.add("S_2x", label, i, source, 2, p, m2, book_usd=book2)
            ev.add("B4_2x", label, i, source, 2, p, S.series_metrics(b4x2), book_usd=book2)
            ev.add("B1", label, i, source, 1, {"weight": 1.0}, m1)
            ev.add("B2", label, i, source, 1, {"weight": 0.5, "every": 30}, mb2)
            ev.add("B5", label, i, source, 1, p, m5)
            for name, series in (("S2", kept2), ("B1", b1), ("B2", b2), ("B4x2", b4x2), ("B5", b5)):
                parts[name].append(series)
            row.update(
                book_2x_usd=book2, metrics_2x=m2, metrics_b5=m5, fold_stats=ctx["wf"][label]["folds"].iloc[i]
            )
            weights.append(plain(res[["w_BTC", "w_ETH"]].loc[w.t0 :].iloc[1:]))
        fold_rows.append(row)
    out = {
        "folds": fold_rows,
        "S": pd.concat(parts["S"]),
        "B4": pd.concat(parts["B4"]),
        "B3": np.hstack(b3_mats),
        "B3_fills": np.column_stack(b3_fills),
        "turnover": pd.concat(parts["turnover"]),
        "trades": np.concatenate(parts["trades"]),
        "fold_metrics": fold_metrics,
    }
    if primary:
        for name in ("S2", "B1", "B2", "B4x2", "B5"):
            out[name] = pd.concat(parts[name])
        out["weights"] = pd.concat(weights)
    return out


def criteria(series: dict, settings) -> dict:
    """E1 (S against B3) and E2 (S against B4, paired bootstrap) on one set of stitched series."""
    e1 = sd.e1_rank(series["S"], series["B3"])
    e2 = sd.paired_bootstrap(series["S"], series["B4"], settings.bootstrap_resamples, sd.MEAN_BLOCK, seed=0)
    return {"e1": e1, "e2": e2}


def b3_rows(ev: Evaluations, label: str, source: str, series: dict, rank: dict) -> None:
    totals = np.prod(1.0 + series["B3"], axis=1) - 1.0
    dds = S.drawdowns(series["B3"])
    for j in range(series["B3"].shape[0]):
        metrics = {
            "rows": series["B3"].shape[1],
            "sharpe": rank["draw_sharpes"][j],
            "total_return": totals[j],
            "max_drawdown": dds[j],
            "worst_day": float(series["B3"][j].min()),
            "fills": int(series["B3_fills"][j].sum()),
        }
        ev.add(
            "B3",
            label,
            "stitched",
            source,
            1,
            None,
            metrics,
            draw=j,
            fold_fills=series["B3_fills"][j],
            targets="S's per-fold targets (kind S rows of the same seed and source); seeds 10*j + fold",
        )


def plateau(ctx: dict, params: list[dict], sharpe_s: float, label: str, ev: Evaluations) -> dict:
    """G5: the 8 steps, each applied to every fold at once, run in H120 and stitched."""
    steps = sd.plateau_steps(params, ctx["limits"])
    table, sharpes = [], []
    for step in steps:
        pieces = []
        for i, w in enumerate(ctx["windows"]):
            res = sd.run_h120(ctx["fn1"], step["params"][i], ctx["K"], w)
            pieces.append(sd.kept_returns(res, w.t0))
        r = pd.concat(pieces)
        m = S.series_metrics(r)
        sharpes.append(m["sharpe"])
        ev.add(
            "plateau",
            label,
            "stitched",
            S.SOURCE,
            1,
            step["params"],
            m,
            param=step["param"],
            factor=step["factor"],
            mark=step["mark"],
            fold_marks=step["fold_marks"],
        )
        table.append(
            {
                "param": step["param"],
                "factor": step["factor"],
                "mark": step["mark"],
                "fold_marks": step["fold_marks"],
                "params": step["params"],
                "sharpe": m["sharpe"],
                "ratio": m["sharpe"] / sharpe_s if sharpe_s else np.nan,
            }
        )
    verdict = sd.plateau_verdict(sharpe_s, sharpes, [s["mark"] for s in steps])
    return {"verdict": verdict, "steps": table, "not_free": sum(s["mark"] != "free" for s in steps)}


def phase_sensitivity(ctx: dict, params: list[dict], label: str, ev: Evaluations) -> dict:
    """Each fold's chosen params with the slice starting j rows earlier, j = 0 .. every - 1 (section 10)."""
    out, runs = [], 0
    for i, (fold, p) in enumerate(zip(ctx["folds"], params, strict=True)):
        sharpes = []
        for j in range(p["every"]):
            w = sd.fold_window(ctx["K"].index, fold.test, warmup=sd.WARMUP + j)
            kept = sd.kept_returns(sd.run_h120(ctx["fn1"], p, ctx["K"], w), w.t0)
            m = S.series_metrics(kept)
            sharpes.append(m["sharpe"])
            ev.add("phase", label, i, S.SOURCE, 1, p, m, j=j, warmup=sd.WARMUP + j)
            runs += 1
        out.append(
            {
                "fold": i,
                "every": p["every"],
                "runs": len(sharpes),
                "min": float(np.min(sharpes)),
                "median": float(np.median(sharpes)),
                "max": float(np.max(sharpes)),
            }
        )
    return {"folds": out, "runs": runs}


def theta_final_in_sample(
    ctx: dict, choice: dict, final_name: str, settings, ev: Evaluations, label: str
) -> dict:
    """theta_final as one fixed configuration over the whole Kraken train panel, IN-SAMPLE (section 10, risk
    description 2): it is the final study's own trial, re-run, and must reproduce its logged returns."""
    theta = S.plain_params(choice["params"])
    res = ctx["fn1"](theta, ctx["K"])
    logged = pd.read_parquet(
        ctx["train"] / final_name / "returns" / f"trial_{choice['trial_number']:06d}.parquet"
    )
    col = logged.iloc[:, 0]
    if not (col.index.equals(res.index) and np.array_equal(col.to_numpy(), res["ret"].to_numpy())):
        raise S.Stop(f"theta_final({label}) re-run does not reproduce its logged trial returns")
    r = res["ret"].to_numpy()
    fills = res.attrs["fills"]
    dd = mc.block_bootstrap_drawdowns(r, mean_block=sd.MEAN_BLOCK, n_sims=settings.mc_sims, seed=0)
    years = (len(r) - 1) / 365
    m = S.series_metrics(r)
    out = {
        "label": "IN-SAMPLE",
        "params": theta,
        **derived(theta),
        "trial_number": choice["trial_number"],
        "max_drawdown": m["max_drawdown"],
        "mc_p5": mc.percentiles(dd, (5,))["p5"],
        "mc_p50": mc.percentiles(dd, (50,))["p50"],
        "worst_day": m["worst_day"],
        "day_p1": float(np.percentile(r, 1)),
        **S.overshoot(res["w_BTC"], res["w_ETH"], ctx["limits"]),
        "legs": len(fills),
        "legs_per_year": len(fills) / years,
        "leg_usd": {**mc.percentiles(fills["usd"]), "max": float(fills["usd"].max())} if len(fills) else {},
        "sharpe": m["sharpe"],
    }
    ev.add(
        "theta_final_in_sample",
        label,
        "all",
        S.SOURCE,
        1,
        theta,
        m,
        **{k: out[k] for k in ("mc_p5", "mc_p50")},
    )
    return out


def s_profile(ctx: dict, trials: pd.DataFrame, final_name: str, settings) -> dict:
    """Score and Sharpe by coin-share bin for every study of this run; for the final study also each trial's
    historical max drawdown and Monte Carlo p5 from its logged returns (section 10)."""
    done = trials[trials["state"] == "COMPLETE"].copy()
    done["s_bin"] = [S.s_bin(s) for s in done["params_coin_share"]]
    by_study = {}
    for study, g in done.groupby("study"):
        by_study[study] = {
            b: {
                "trials": len(h),
                "score_median": float(h["value"].median()),
                "score_mean": float(h["value"].mean()),
                "sharpe_median": float(h["sharpe"].median()),
            }
            for b, h in g.groupby("s_bin")
        }
    m = load_trial_returns(final_name, ctx["train"]).dropna()
    final = done[done["study"] == final_name].set_index("number")
    rows = []
    for col in m.columns:
        n = int(col[1:])
        r = m[col].to_numpy()
        dd = mc.block_bootstrap_drawdowns(
            r, mean_block=sd.MEAN_BLOCK, n_sims=settings.profile_mc_sims, seed=0
        )
        rows.append(
            {
                "s_bin": final.loc[n, "s_bin"],
                "max_drawdown": mc.max_drawdown(r),
                "mc_p5": mc.percentiles(dd, (5,))["p5"],
            }
        )
    risk = pd.DataFrame(rows)
    final_risk = (
        {
            b: {
                "trials": len(h),
                "max_drawdown_median": float(h["max_drawdown"].median()),
                "max_drawdown_worst": float(h["max_drawdown"].min()),
                "mc_p5_median": float(h["mc_p5"].median()),
                "mc_p5_worst": float(h["mc_p5"].min()),
            }
            for b, h in risk.groupby("s_bin")
        }
        if len(risk)
        else {}
    )
    return {"by_study": by_study, "final_risk": final_risk}


def seed_report(ctx: dict, label: str, ev: Evaluations, settings) -> dict:
    """Everything sections 9-10 report for one seed, on Kraken train."""
    wf, train, K, limits = ctx["wf"][label], ctx["train"], ctx["K"], ctx["limits"]
    params = [S.plain_params({n: wf["folds"].iloc[i][f"p_{n}"] for n in sd.PARAM_NAMES}) for i in range(4)]
    series = run_comparators(ctx, K, params, label, S.SOURCE, None, ev, settings)
    s_ret = series["S"]
    if not (
        s_ret.index.equals(wf["oos_returns"].index)
        and np.array_equal(s_ret.to_numpy(), wf["oos_returns"].to_numpy())
    ):
        raise S.Stop(f"seed {label}: the stitched H120 series is not walk_forward_optimize's oos_returns")
    sh = {k: S.sharpe(series[k]) for k in ("S", "S2", "B1", "B2", "B4", "B4x2", "B5")}
    crit = criteria(series, settings)
    b3_rows(ev, label, S.SOURCE, series, crit["e1"])
    for name, kind, cost_x in (
        ("S", "S", 1),
        ("S2", "S_2x", 2),
        ("B1", "B1", 1),
        ("B2", "B2", 1),
        ("B4", "B4", 1),
        ("B5", "B5", 1),
    ):
        ev.add(
            kind,
            label,
            "stitched",
            S.SOURCE,
            cost_x,
            params,
            S.stitched_metrics(series[name], series["fold_metrics"][name]),
        )

    combined = {
        "oos_returns": s_ret,
        "wf_efficiency": wf["wf_efficiency"],
        "studies": ctx["studies"],
        "total_trials": ctx["n_raw"],
    }
    rep = overfitting_report(combined, train)
    trial_sharpes = ctx["trial_sharpes"]
    strict = (
        stats.deflated_sharpe_ratio(s_ret.to_numpy(), trial_sharpes, n_trials=ctx["n_raw"] + S.STRICT_EXTRA)[
            "dsr"
        ]
        if trial_sharpes
        else float("nan")
    )
    g5 = plateau(ctx, params, sh["S"], label, ev)
    table = sd.regime_table(K[("BTC", "close")], s_ret.index)
    regimes = sd.regime_split(s_ret, table, benchmark=series["B4"])
    budget = ctx["g6"]["max_drawdown_budget"]
    gate_numbers = {k: sh[k] for k in ("S", "S2", "B1", "B2")}
    gate_table = S.gate_table(gate_numbers, rep, g5["verdict"], regimes["pass"], budget)
    e = {"E1": crit["e1"]["holds"], "E2": crit["e2"]["holds"], "E3": bool(sh["S2"] > sh["B4x2"])}

    # descriptions (section 10)
    shuffled = mc.shuffled_trade_drawdowns(series["trades"], n_sims=settings.shuffle_sims, seed=0)
    degraded = mc.degrade_execution(
        s_ret.to_numpy(),
        series["turnover"].to_numpy(),
        extra_cost_bps=S.DEGRADE_BPS,
        n_sims=settings.degrade_sims,
        seed=0,
    )
    k_total = int(sum(f["k"] for f in series["folds"]))
    books0 = series["folds"][0]["book_usd"]
    span = {}
    for i, p in enumerate(params):
        r = sd.static_span_b4(K, ctx["windows"][0], ctx["windows"][-1], p, ctx["costs1"], books0, s_ret.index)
        span[i] = r
        ev.add("B4_span", label, f"targets of fold {i}", S.SOURCE, 1, p, S.series_metrics(r))
    weights = series["weights"]
    unpaid = []
    for i in range(len(params) - 1):
        nxt = sd.targets(params[i + 1])
        last = weights.loc[ctx["windows"][i].last]
        unpaid.append(abs(nxt[0] - last["w_BTC"]) + abs(nxt[1] - last["w_ETH"]))
    folds_out = []
    for f in series["folds"]:
        fs = f.pop("fold_stats")
        f.update(
            study=fs["study"],
            is_sharpe=fs["is_sharpe"],
            oos_sharpe=fs["oos_sharpe"],
            wf_efficiency=fs["oos_sharpe"] / fs["is_sharpe"] if fs["is_sharpe"] > 0 else float("nan"),
            trials=int(fs["trials"]),
            neighbourhood=neighbourhood(S.trial_table(train, [fs["study"]]), f["params"]),
        )
        folds_out.append(f)
    distinct_s = len({p["coin_share"] for p in params}) > 1
    phase = phase_sensitivity(ctx, params, label, ev)
    fm = series["fold_metrics"]
    stitched = {
        "S": S.stitched_metrics(s_ret, fm["S"]),
        "S_2x": S.stitched_metrics(series["S2"], fm["S2"]),
        "B1": S.stitched_metrics(series["B1"], fm["B1"]),
        "B2": S.stitched_metrics(series["B2"], fm["B2"]),
        "B3": S.b3_summary(series["B3"], crit["e1"]),
        "B4": S.stitched_metrics(series["B4"], fm["B4"]),
        "B4_2x": S.series_metrics(series["B4x2"]),
        "B5": S.stitched_metrics(series["B5"], fm["B5"]),
        "B4_span": {i: S.series_metrics(r) for i, r in span.items()},
    }
    if stitched["S"]["fills"] != k_total:
        raise S.Stop(f"seed {label}: the stitched fill count is not the sum of k_i")
    if stitched["B4"]["fills"] or stitched["B4"]["cost"]:
        raise S.Stop(
            f"seed {label}: B4 traded inside the kept rows (section 8: its only buy is at the open of t0)"
        )
    oos = {
        f"S_{label}": s_ret,
        f"S2x_{label}": series["S2"],
        f"B4_{label}": series["B4"],
        f"B5_{label}": series["B5"],
        "B1": series["B1"],
        "B2": series["B2"],
        **{f"B4span_{label}_fold{i}": r for i, r in span.items()},
        **{
            f"B3_{label}_p{q}": pd.Series(np.percentile(series["B3"], q, axis=0), index=s_ret.index)
            for q in (5, 50, 95)
        },
    }
    return {
        "params": params,
        "series": series,
        "oos": oos,
        "rep": rep,
        "sharpe": sh["S"],
        "gates": gate_table,
        "E": e,
        "report": {
            "folds": folds_out,
            "wf_efficiency": wf["wf_efficiency"],
            "stitched": stitched,
            "e1": {k: crit["e1"][k] for k in ("sharpe", "p5", "p50", "p95", "rank_p", "holds")},
            "e2": {k: crit["e2"][k] for k in ("d", "p", "holds", "n_resamples", "mean_block", "seed")},
            "e3": {"sharpe_S_2x": sh["S2"], "sharpe_B4_2x": sh["B4x2"], "holds": e["E3"]},
            "gates": gate_table,
            "gate_inputs": S.gate_inputs(gate_numbers, rep, budget),
            "overfitting_report": rep,
            "dsr": {
                "effective": rep["dsr_effective_count"],
                "raw": rep["dsr_raw_count"],
                "strict": strict,
                "n_effective": rep["trials_effective"],
                "n_raw": ctx["n_raw"],
                "n_strict": ctx["n_raw"] + S.STRICT_EXTRA,
            },
            "plateau": g5,
            "regimes": {
                "split": regimes,
                "months": table.groupby("month")
                .first()[["month_ret", "regime"]]
                .reset_index()
                .to_dict(orient="records"),
            },
            "monte_carlo": {
                "block_p5": rep["mc_drawdown_worst5pct"],
                "block_p50": rep["mc_drawdown_median"],
                "shuffled_trades": {"periods": len(series["trades"]), **mc.percentiles(shuffled, (5, 50))},
                "degraded_execution": {
                    **mc.percentiles(degraded),
                    "S_total": stitched["S"]["total_return"],
                    "extra_cost_bps": S.DEGRADE_BPS,
                },
            },
            "trades_per_parameter": {
                "value": k_total / len(sd.PARAM_NAMES),
                "kept_fills": k_total,
                "flag": k_total / len(sd.PARAM_NAMES) < S.TRADES_PER_PARAM_FLAG,
            },
            "correlations": {
                "B1": float(np.corrcoef(s_ret, series["B1"])[0, 1]),
                "B2": float(np.corrcoef(s_ret, series["B2"])[0, 1]),
            },
            "phase_sensitivity": phase,
            "risk": {
                "folds": [
                    {
                        "fold": f["fold"],
                        "coin_share": f["params"]["coin_share"],
                        "w_btc": f["w_btc"],
                        "w_eth": f["w_eth"],
                        "max_drawdown": f["metrics"]["max_drawdown"],
                        "worst_day": f["metrics"]["worst_day"],
                    }
                    for f in folds_out
                ],
                "stitched_overshoot": S.overshoot(weights["w_BTC"], weights["w_ETH"], limits),
                "note": (
                    "The folds chose different coin shares, so S's Monte Carlo p5 is not the drawdown of any one "
                    "shippable configuration."
                    if distinct_s
                    else "Every fold chose the same coin share; S still mixes the folds' other parameters."
                ),
            },
            "unpaid_turnover": {"boundaries": unpaid, "total": float(np.sum(unpaid))},
        },
    }


def binance_report(ctx: dict, params: list[dict], ev: Evaluations, settings) -> dict:
    """E5: seed A's per-fold params on the Binance panel, same closes, its own k_i and book, the same B3 seeds and
    bootstrap."""
    series = run_comparators(ctx, ctx["Bn"], params, "A", S.ROBUSTNESS, ctx["K"], ev, settings)
    crit = criteria(series, settings)
    b3_rows(ev, "A", S.ROBUSTNESS, series, crit["e1"])
    ev.add(
        "S",
        "A",
        "stitched",
        S.ROBUSTNESS,
        1,
        params,
        S.stitched_metrics(series["S"], series["fold_metrics"]["S"]),
    )
    ev.add(
        "B4",
        "A",
        "stitched",
        S.ROBUSTNESS,
        1,
        params,
        S.stitched_metrics(series["B4"], series["fold_metrics"]["B4"]),
    )
    return {
        "series": series,
        "holds": bool(crit["e1"]["holds"] and crit["e2"]["holds"]),
        "report": {
            "folds": [{k: f[k] for k in ("fold", "k", "book_usd", "metrics")} for f in series["folds"]],
            "stitched": {
                "S": S.stitched_metrics(series["S"], series["fold_metrics"]["S"]),
                "B4": S.stitched_metrics(series["B4"], series["fold_metrics"]["B4"]),
                "B3": S.b3_summary(series["B3"], crit["e1"]),
            },
            "e1": {k: crit["e1"][k] for k in ("sharpe", "p5", "p50", "p95", "rank_p", "holds")},
            "e2": {k: crit["e2"][k] for k in ("d", "p", "holds", "n_resamples", "mean_block", "seed")},
        },
    }


def pbo_table(studies: list[str], train: Path) -> dict:
    out = {}
    for study in studies:
        res = sd.study_pbo(study, train)
        if res is None:
            out[study] = None
            continue
        logits = np.asarray(res["logits"], dtype=float)
        out[study] = {
            "pbo": res["pbo"],
            "n_combinations": res["n_combinations"],
            "n_trials": res["n_trials"],
            "logits": {**mc.percentiles(logits), "share_le_0": float(np.mean(logits <= 0))},
        }
    return out


def searches(ctx: dict, k: int, context: dict, settings, finals: dict) -> None:
    """Section 7: per seed, the 4 walk-forward studies and the final study on all train rows (seed + 4000)."""
    for label, seed in S.SEEDS.items():
        tag = S.study_tag(seed, k)
        cfg = S.search_config(seed, settings)
        t = time.time()
        ctx["wf"][label] = walk_forward_optimize(
            tag,
            ctx["fn1"],
            list(sd.SPECS),
            ctx["K"],
            ctx["folds"],
            ctx["train"],
            cfg,
            warmup=sd.WARMUP,
            context={**context, "seed": seed},
        )
        final_name = f"{tag}_final"
        trials = run_study(
            final_name,
            ctx["fn1"],
            list(sd.SPECS),
            ctx["K"],
            ctx["train"],
            replace(cfg, seed=seed + S.FINAL_SEED_OFFSET),
            {**context, "seed": seed},
        )
        finals[label] = {"study": final_name, "choice": stable_region(trials, sd.SPECS, k=S.STABLE_K)}
        print(
            f"seed {label}: 5 studies in {time.time() - t:.1f}s, OOS Sharpe {ctx['wf'][label]['oos_sharpe']:.3f}",
            flush=True,
        )


def train_phase(args, summary: dict, run_dir: Path, ctx: dict, settings) -> dict:
    """Load the train panels and run everything; returns the results."""
    start, train, k = summary["start"], ctx["train"], summary["run"]
    loader = S.synthetic_bar_loader(args.synthetic) if args.synthetic is not None else None
    panels = {}
    for source in (S.SOURCE, S.ROBUSTNESS):
        panel = S.load_study_panel(
            source,
            S.TRAIN_LAST_CLOSE,
            catalog_dir=Path(args.catalog_dir),
            config_dir=ctx["config_dir"],
            loader=loader,
        )
        if len(panel) != S.ROWS["train"][source]:
            raise S.Stop(
                f"{source}: {len(panel)} train rows, the plan counts {S.ROWS['train'][source]} (section 3)"
            )
        if panel.attrs["snapshot_id"] != start["snapshot"]["snapshot_id"]:
            raise S.Stop(
                f"{source}: snapshot {panel.attrs['snapshot_id']} is not the one SNAPSHOT.json names"
            )
        panels[source] = panel
    summary["panels"] = {s: S.panel_record(p) for s, p in panels.items()}
    summary["status"] = "panels loaded"
    S.write_json(run_dir / "summary.json", summary)
    K, Bn = panels[S.SOURCE], panels[S.ROBUSTNESS]
    print(f"panels: Kraken {len(K)} rows, Binance {len(Bn)} rows (train)", flush=True)

    folds = walk_forward(len(K), train_size=S.TRAIN_SIZE, test_size=S.TEST_SIZE, expanding=True)
    ctx.update(K=K, Bn=Bn, folds=folds, windows=[sd.fold_window(K.index, f.test) for f in folds], wf={})
    context = {
        "snapshot_id": start["snapshot"]["snapshot_id"],
        "bars_sha256": start["snapshot"]["bars_content_sha256"],
        "git_commit": start["git"]["commit"],
        "git_dirty": start["git"]["dirty"],
        "config_hash": start["config_hash"],
        "source": S.SOURCE,
        "interval": S.INTERVAL,
        "run": k,
        "data": start["data"],
        "min_cash": start["risk_limits"]["min_cash"],
        "max_coin": start["risk_limits"]["max_coin"],
        "max_drawdown_budget_pct": S.jsonable(start["risk_limits"]["max_drawdown_budget_pct"]),
        "risk_levels_sha256": start["risk_limits"]["sha256"],
        "label": S.LABEL,
    }
    finals = {}
    failure_log = S.FailureLog()
    with failure_log:
        searches(ctx, k, context, settings, finals)
    studies = S.study_dirs(train)
    trials_all = S.trial_table(train, studies)
    this = (trials_all["run"] == k).to_numpy()
    failed_rows = this & (trials_all["state"] != "COMPLETE").to_numpy()
    trials_all.loc[failed_rows, "fail_reason"] = [
        S.failure_reason(row, failure_log.records) for _, row in trials_all.loc[failed_rows].iterrows()
    ]
    for j in range(k):  # earlier runs' reasons, from their summaries
        prev = json.loads((train / f"run{j}" / "summary.json").read_text()).get("results", {})
        for f in prev.get("failed_trials", []):
            hit = (trials_all["study"] == f["study"]) & (trials_all["number"] == f["number"])
            trials_all.loc[hit, "fail_reason"] = f.get("fail_reason", "")
    ctx.update(studies=studies, n_raw=len(trials_all), trial_sharpes=sd.report_trial_sharpes(studies, train))
    this_run = trials_all[this]
    failed = trials_all[failed_rows]
    ev = Evaluations(k)
    seeds = {}
    for label in S.SEEDS:
        t = time.time()
        seeds[label] = seed_report(ctx, label, ev, settings)
        seeds[label]["report"]["theta_final"] = theta_final_in_sample(
            ctx, finals[label]["choice"], finals[label]["study"], settings, ev, label
        )
        seeds[label]["report"]["s_profile"] = s_profile(
            ctx, this_run[this_run["seed"] == S.SEEDS[label]], finals[label]["study"], settings
        )
        print(
            f"seed {label}: evaluated in {time.time() - t:.1f}s; E1 {seeds[label]['E']['E1']}, "
            f"E2 {seeds[label]['E']['E2']}, gates {seeds[label]['gates']}",
            flush=True,
        )
    bn = binance_report(ctx, seeds["A"]["params"], ev, settings)

    a, b = seeds["A"], seeds["B"]
    frag = S.fragility(
        {**a["E"], "gates": a["gates"], "sharpe": a["sharpe"]},
        {**b["E"], "gates": b["gates"], "sharpe": b["sharpe"]},
    )
    e = {**a["E"], "E4": not frag["fragile"], "E5": bn["holds"]}
    verdict = S.train_verdict(e)
    distances = {
        "folds": [S.unit_distance(p, q) for p, q in zip(a["params"], b["params"], strict=True)],
        "final": S.unit_distance(finals["A"]["choice"]["params"], finals["B"]["choice"]["params"]),
    }

    # outputs
    oos = pd.DataFrame(
        {
            **a["oos"],
            **b["oos"],
            "S_binance_A": bn["series"]["S"],
            "B4_binance_A": bn["series"]["B4"],
            **{f"B3_binance_A_p{q}": np.percentile(bn["series"]["B3"], q, axis=0) for q in (5, 50, 95)},
        }
    )
    oos.to_parquet(run_dir / "oos.parquet")
    evals = ev.frame()
    evals.to_parquet(run_dir / "evaluations.parquet")
    trials_all.to_parquet(run_dir / "trials.parquet")
    tracked = S.tracked_dir(Path(args.out_dir), args.synthetic is not None)
    tracked.mkdir(parents=True, exist_ok=True)
    trials_all.to_csv(tracked / "trials.csv", index=False)
    every_run = [
        pd.read_parquet(p) for j in range(k + 1) if (p := train / f"run{j}" / "evaluations.parquet").is_file()
    ]
    pd.concat(every_run, ignore_index=True).to_csv(tracked / "evaluations.csv", index=False)

    earlier = {}
    for j in range(k):
        prev = json.loads((train / f"run{j}" / "summary.json").read_text())
        earlier[j] = {
            "status": prev.get("status"),
            "verdict": prev.get("results", {}).get("train_verdict"),
            "gates_A": prev.get("results", {}).get("seeds", {}).get("A", {}).get("gates"),
        }
    return {
        "label": S.LABEL,
        "train_verdict": verdict,
        "E": e,
        "fragility": frag,
        "headline_if_edge": S.headline("EDGE", a["gates"]),
        "seeds": {
            lab: {
                "params": s["params"],
                "sharpe": s["sharpe"],
                "gates": s["gates"],
                "E": s["E"],
                **s["report"],
            }
            for lab, s in seeds.items()
        },
        "theta_final": {
            lab: {
                "study": f["study"],
                "trial_number": f["choice"]["trial_number"],
                "params": S.plain_params(f["choice"]["params"]),
            }
            for lab, f in finals.items()
        },
        "binance": bn["report"],
        "seed_distance_unit": distances,
        "trials": {
            "n_raw": ctx["n_raw"],
            "n_strict": ctx["n_raw"] + S.STRICT_EXTRA,
            "studies": studies,
            "this_run": len(this_run),
            "phase_runs": {lab: s["report"]["phase_sensitivity"]["runs"] for lab, s in seeds.items()},
            "evaluations": len(evals),
        },
        "pbo_per_study": pbo_table(studies, train),
        "failed_trials": S.jsonable(
            failed[
                ["study", "number", "state", "fail_reason", *(f"params_{n}" for n in sd.PARAM_NAMES)]
            ].to_dict(orient="records")
        ),
        "failure_log": failure_log.records,
        "triage_required": bool(len(failed)),
        "earlier_runs": earlier,
    }


def run(args) -> int:
    synthetic = args.synthetic is not None
    if not synthetic and (args.fast or args.allow_dirty):
        raise S.Refusal("--fast and --allow-dirty are for synthetic dry runs only")
    if args.amendment == 0:
        raise S.Refusal("--amendment 0: run 0 is run without --amendment")
    k = 0 if args.amendment is None else args.amendment
    out = Path(args.out_dir)
    config_dir = Path(args.config_dir) if args.config_dir else None
    S.check_paths(out, config_dir, Path(args.catalog_dir), synthetic)
    train = out / "train"
    check_layout(train, k)
    data = "synthetic" if synthetic else "real"
    if k:
        check_earlier_runs(train, k, data, bool(args.fast))
    check_runlog(S.runlog_path(out, synthetic), k, data)
    if k and not synthetic and not S.amendment_row_present(S.PLAN.read_text(), k):
        raise S.Refusal(
            f"--amendment {k}: PLAN.md section 13 has no '- **Amendment run {k}' row (stop rule 7)"
        )
    git = S.git_state()
    if git["dirty"] and not (synthetic and args.allow_dirty):
        raise S.Refusal(
            "the git tree is dirty (git status --porcelain --untracked-files=all): commit first. "
            f"Changes: {git['changes'][:10]}"
        )
    hashes = S.file_hashes(config_dir)
    snapshot = S.read_snapshot(Path(args.catalog_dir), synthetic)
    try:
        limits = sd.steady_limits(config_dir)
        corners = sd.check_box(sd.SPECS, limits)
    except ValueError as exc:
        raise S.Refusal(f"the Steady limits as read refuse the search box (section 5): {exc}") from exc
    settings = S.FAST if args.fast else S.PLAN_SETTINGS
    start = {
        "utc": S.utc_now(),
        "script": "run_train.py",
        "data": data,
        "synthetic_seed": args.synthetic,
        "git": git,
        "config_hash": S.config_hash(hashes),
        "file_hashes": hashes,
        "snapshot": snapshot,
        "risk_limits": limits,
        "g6_budget": g6_budget(train, k, limits),
        "box_corners": corners,
        "settings": asdict(settings),
        "fast": bool(args.fast),
        "config_dir": str(config_dir) if config_dir else None,
        "label": S.LABEL,
    }
    S.append_runlog(
        S.runlog_path(out, synthetic),
        {
            "utc": start["utc"],
            "script": "run_train.py",
            "run": k,
            "commit": git["commit"],
            "dirty": git["dirty"],
            "config_hash": start["config_hash"],
            "snapshot_id": snapshot["snapshot_id"],
            "data": start["data"],
            "out_dir": str(out),
        },
    )
    run_dir = train / f"run{k}"
    run_dir.mkdir(parents=True)
    summary = {"study": S.STUDY, "run": k, "status": "started", "start": S.jsonable(start)}
    S.write_json(run_dir / "summary.json", summary)
    print(
        f"run {k} ({start['data']}) started; config hash {start['config_hash'][:16]}; "
        f"limits min_cash {limits['min_cash']}, max_coin {limits['max_coin']}, budget "
        f"{limits['max_drawdown_budget_pct']!r}",
        flush=True,
    )
    costs1 = Costs.from_yaml(costs_path(config_dir))
    costs2 = costs1.stressed()
    ctx = {
        "train": train,
        "config_dir": config_dir,
        "limits": limits,
        "g6": start["g6_budget"],
        "costs1": costs1,
        "costs2": costs2,
        "fn1": partial(sd.steady_backtest, limits=limits, costs=costs1),
        "fn2": partial(sd.steady_backtest, limits=limits, costs=costs2),
    }
    t = time.time()
    try:
        results = train_phase(args, summary, run_dir, ctx, settings)
        if summary["start"] != S.jsonable(start):
            raise S.Stop("the start fields changed during the run")
    except (HoldoutWindowError, sd.SliceMismatchError, S.Stop) as exc:
        summary["status"] = f"stopped: {type(exc).__name__}: {exc}"
        S.write_json(run_dir / "summary.json", summary)
        print(f"STOP: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        summary["status"] = f"crashed: {type(exc).__name__}: {exc}"
        S.write_json(run_dir / "summary.json", summary)
        raise
    summary["results"] = results
    summary["runtime_s"] = time.time() - t
    summary["status"] = "complete"
    S.write_json(run_dir / "summary.json", summary)
    v = results["train_verdict"]
    print(
        f"run {k} complete in {time.time() - t:.1f}s. Train verdict: {v['verdict']} (E {results['E']}); "
        f"gates A {results['seeds']['A']['gates']}; failed trials {len(results['failed_trials'])}",
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
