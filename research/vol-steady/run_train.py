"""Train phase of the vol-steady study: searches, comparators, luck controls, gates, verdict (PLAN.md sections 3-16).

SCOUTING ONLY: the reference portfolio engine (lab.runner.trend's executor via lab.runner.volsteady), not
NautilusTrader (AGENTS.md hard rule 3), with PLACEHOLDER costs. Reads only bars closing up to 2023-01-01 00:00 UTC (the
last train close), through lab.data.panel.load_panel; never the validate or test windows. Trend-steady's run_train.py
(TP) adapted: the volatility rule, P as share changes, and no stop-loss variant (section 11A).

    uv run python research/vol-steady/run_train.py                                   # run 0 on real data
    uv run python research/vol-steady/run_train.py --amendment 1 --trigger b         # amendment run 1
    uv run python research/vol-steady/run_train.py --synthetic 7 --fast --out-dir <scratch>   # dry run

Start guards, all before anything is written or loaded: a real run uses the pinned folders only (results/
vol-steady, config/, data/catalog) and a dry run never writes into results/vol-steady or the repo; run 0 refuses
if ``<out>/train/`` exists; ``--amendment k`` refuses unless 1 <= k <= 2, ``train/run<k-1>/summary.json`` exists,
every earlier run has the same data and ``--fast`` setting, neither ``train/run<k>/`` nor an ``_a<k>_`` study exists,
``--trigger`` is given (stop rule 18) and (real data) PLAN.md holds the row ``- **Amendment run k``; the RUNLOG must
not hold this run number; a dirty git tree is refused (dry runs may pass ``--allow-dirty``); a real run needs
amendments A1 and A0 in PLAN.md section 15 (TP M27); the snapshot's bars hash (stop rule 2); the branch guard (stop
rule 11); every target set the run can order (stop rule 12, every s x q); the projection guard (stop rule 17: above 60
CPU-minutes a real run refuses). Then, before any bar is read: one RUNLOG line and ``train/run<k>/summary.json`` with
the start fields.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.external import HoldoutWindowError
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.search.report import overfitting_report
from lab.search.stability import stable_region
from lab.search.study import load_trial_returns, run_study
from lab.search.walkforward import walk_forward_optimize
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward


def _study_module():
    name = "vol_steady_study"
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
        "--out-dir", default=str(S.DEFAULT_OUT), help="results folder (default results/vol-steady)"
    )
    ap.add_argument("--catalog-dir", default=str(S.DEFAULT_CATALOG))
    ap.add_argument(
        "--config-dir", default=None, help="folder with costs.yaml, splits.yaml, risk_levels.yaml"
    )
    ap.add_argument("--amendment", type=int, default=None, metavar="K", help="amendment run K (1 or 2)")
    ap.add_argument(
        "--trigger", default=None, help="an amendment run's trigger: a, b, c or 'other, after the verdict'"
    )
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED", help="dry run on synthetic bars")
    ap.add_argument("--fast", action="store_true", help="dry runs only: small trial and simulation counts")
    ap.add_argument("--allow-dirty", action="store_true", help="dry runs only: run on a dirty git tree")
    return ap.parse_args(argv)


# ------------------------------------------------------------------------------------------- start guards


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
            f"--amendment {k}: amendment runs are numbered 1..{S.MAX_AMENDMENTS} (run 0 has no --amendment). If a "
            "third rerun would be needed, stop: the verdict is INCONCLUSIVE (stop rule 7)"
        )
    if not (train / f"run{k - 1}" / "summary.json").is_file():
        raise S.Refusal(f"--amendment {k}: {train / f'run{k - 1}' / 'summary.json'} does not exist")
    if (train / f"run{k}").exists():
        raise S.Refusal(f"--amendment {k}: {train / f'run{k}'} exists (a run is never resumed: stop rule 6)")
    clash = [p.name for p in train.iterdir() if f"_a{k}_" in p.name]
    if clash:
        raise S.Refusal(f"--amendment {k}: studies of amendment run {k} exist: {clash}")


def check_earlier_runs(train: Path, k: int, data: str, fast: bool) -> None:
    """INTERPRETATIONS["same_kind_of_run"]."""
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
    """INTERPRETATIONS["runlog_guard"]."""
    for line in S.runlog_entries(path):
        if line.get("script") == "run_train.py" and line.get("run") == k and line.get("data") == data:
            raise S.Refusal(
                f"{path} already records {data} run {k} (started {line.get('utc')}): a deleted run is not rerun "
                "under its number (stop rules 6-7)"
            )


def g6_budget(train: Path, k: int, limits: dict) -> dict:
    """G6's budget: run 0's train-start reading for the whole study (INTERPRETATIONS["g6_budget"])."""
    path = train / "run0" / "summary.json"
    try:
        source = limits if k == 0 else json.loads(path.read_text())["start"]["risk_limits"]
        return {
            "source_run": 0,
            "max_drawdown_budget": source["max_drawdown_budget"],
            "max_drawdown_budget_pct": source["max_drawdown_budget_pct"],
            "sha256": source["sha256"],
        }
    except (OSError, ValueError, KeyError) as exc:
        raise S.Refusal(f"G6 needs run 0's train-start reading: {path}: {exc!r}") from exc


# ------------------------------------------------------------------------------------------- the record


class Evaluations:
    """Every run that is not a search trial (section 14): one row each, the strict count's runs marked."""

    def __init__(self, run: int):
        self.run = run
        self.rows: list[dict] = []

    def add(
        self, kind, seed, fold, source, cost_x, params, metrics: dict, *, counted=False, offset=None, **extra
    ):
        self.rows.append(
            {
                "run": self.run,
                "kind": kind,
                "seed": seed,
                "fold": str(fold),
                "source": source,
                "cost_x": cost_x,
                "offset": -1 if offset is None else int(offset),
                "counted": bool(counted),
                "params": json.dumps(S.jsonable(params), sort_keys=True) if params is not None else "",
                **{
                    k: metrics.get(k, np.nan)
                    for k in ("rows", "sharpe", "total_return", "max_drawdown", "worst_day")
                },
                **{k: metrics.get(k, np.nan) for k in ("fills", "turnover", "cost")},
                "extra": json.dumps(S.jsonable(extra), sort_keys=True),
                "label": S.LABEL,
            }
        )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def result_metrics(res: pd.DataFrame, t0) -> dict:
    kept = res.loc[pd.Timestamp(t0) :].iloc[1:]
    out = S.series_metrics(kept["ret"])
    out["fills"] = int((kept["turnover"] > 0).sum())
    out["turnover"] = float(kept["turnover"].sum())
    out["cost"] = float(kept["cost"].sum())
    return out


def kept_metrics(res: pd.DataFrame, kept: pd.DatetimeIndex) -> dict:
    rows = res.loc[kept]
    out = S.series_metrics(rows["ret"])
    out["fills"] = int((rows["turnover"] > 0).sum())
    out["turnover"] = float(rows["turnover"].sum())
    out["cost"] = float(rows["cost"].sum())
    return out


def log_bundle(
    ev: Evaluations, b: dict, kind: str, seed, source: str, windows, *, counted=False, cost_x=1, **extra
):
    """One row per fold piece and one stitched row (the counted one) of a bundle's S."""
    for i, (r, w, p) in enumerate(zip(b["runs"], windows, b["params"], strict=True)):
        ev.add(kind, seed, i, source, cost_x, p, result_metrics(r, w.t0), **extra)
    ev.add(
        kind,
        seed,
        "stitched",
        source,
        cost_x,
        b["params"],
        S.series_metrics(b["S"]),
        counted=counted,
        **extra,
    )


def log_shifts(ev: Evaluations, kind: str, seed, source: str, series: dict, **extra) -> None:
    for u, r in sorted(series.items()):
        ev.add(kind, seed, "span", source, 1, None, S.series_metrics(r), offset=u, **extra)


def neighbourhood(trials: pd.DataFrame, chosen: dict) -> dict:
    """The stable region's 10 neighbours (ranges and scores) and the raw best trial (section 7)."""
    hood = sd.stable_neighbours(trials, V.SPECS, k=S.STABLE_K)
    pick = stable_region(trials, list(V.SPECS), k=S.STABLE_K)
    if S.plain_params(pick["params"]) != chosen:
        raise S.Stop("the stable region recomputed here is not the one walk_forward_optimize traded")
    nb = hood["neighbours"]
    return {
        "trial_number": hood["trial_number"],
        "neighbourhood_score": hood["neighbourhood_score"],
        "ranges": {
            n: [float(nb[f"params_{n}"].min()), float(nb[f"params_{n}"].max())] for n in V.PARAM_NAMES
        },
        "neighbours": S.jsonable(nb.to_dict(orient="records")),
        "raw_best_params": S.plain_params(pick["raw_best_params"]),
        "raw_best_score": pick["raw_best_score"],
    }


# ------------------------------------------------------------------------------------------- the numbers


def e2(ctx, s: pd.Series, n0: pd.Series, **kw) -> dict:
    """E2's paired bootstrap at the run's resample count (tallied for the projection's table)."""
    ctx["tally"].add("bootstrap")
    return T.e2_test(s, n0, n_resamples=ctx["settings"].bootstrap_resamples, **kw)


def kept_log(results, windows) -> pd.DataFrame:
    """INTERPRETATIONS["orders_in_kept_rows"] for fold runs."""
    return pd.concat([T.order_log(r, w.t0) for r, w in zip(results, windows, strict=True)], ignore_index=True)


def r1(ctx, log: pd.DataFrame) -> dict:
    return T.r1_check(log, ctx["kept"], ctx["covered"])


def fixed_r1(ctx, run: pd.DataFrame) -> dict:
    """R1 of a fixed run over the kept rows, with that run's order hash (so a wrong run moves the record)."""
    return {**r1(ctx, S.fixed_log(run, ctx["kept"])), "order_hash": [run.attrs["order_hash"]]}


def g7_parts(ctx, series: pd.Series) -> dict:
    """G7's numbers on the full rows and without BTC's best and two best bar-years: Sharpe of S, B1 and B2."""
    out = {}
    for name, mask in ctx["g7_masks"].items():
        a, b1, b2 = (S.sharpe(S.masked(x, mask)) for x in (series, ctx["B1"], ctx["B2"]))
        out[name] = {"sharpe": a, "B1": b1, "B2": b2, "holds": g7_part({"sharpe": a, "B1": b1, "B2": b2})}
    return out


def g8(ctx, series: pd.Series, n0: pd.Series) -> dict:
    split = sd.regime_split(series, ctx["table"], benchmark=n0)
    return {"split": split, "excess_pass": T.g8_excess_pass(split), "literal_pass": split["pass"]}


def e7_removals(ctx, b: dict) -> list[dict]:
    """E7's two removals: each item's numbers on the rows without BTC's best and two best years, and its outcome by
    :func:`removal_items`."""
    out = []
    for years in (ctx["years"][:1], ctx["years"][:2]):
        mask = T.without_years(b["kept"], years)
        row = {"removed": years, "rows": int(mask.sum())}
        row["e1"] = S.e1_numbers(T.e1_test(b["R0"].to_numpy(dtype=float), b["shifts"], b["W"], keep=mask))
        row["e2"] = S.e2_numbers(e2(ctx, S.masked(b["S"], mask), S.masked(b["N0"], mask)))
        sm, xm = S.masked(b["S"], mask), S.masked(b["X"], mask)
        row["e3"] = [S.drawdown_of(sm), S.g6_of(sm), S.drawdown_of(xm), S.g6_of(xm)]
        row["e4"] = [S.sharpe(S.masked(b["S2"], mask)), S.sharpe(S.masked(b["N0_2"], mask))]
        out.append({**row, **removal_items(row)})
    return out


# ------------------------------------------------------------------------------------- the decision rules
# Each outcome below reads only the numbers it is given (recorded next to it in summary.json), so it can be checked
# by hand with numbers that separate every wiring choice, and the numbers can be rebuilt from their inputs (#47).


def g7_part(p: Mapping):
    """G7 at one point: Sharpe(S) above B1's AND above B2's on the same rows; MISSING when a number is NaN."""
    return S.point(p["sharpe"] > p["B1"] and p["sharpe"] > p["B2"], p["sharpe"], p["B1"], p["B2"])


def removal_items(row: Mapping) -> dict:
    """E7's items on one removal's numbers."""
    return {
        "E1": T.rank_holds(row["e1"]["rank_p"]),
        "E2": T.e2_holds(row["e2"]["d"], row["e2"]["p"]),
        "E3": T.e3_holds(*row["e3"]),
        "E4": bool(row["e4"][0] > row["e4"][1]),
    }


def s_items(n: Mapping, budget) -> dict:
    """The criteria and the gates measured at one seed's S (E5(a)'s list, M12), from its numbers record."""
    sh, rep, act = n["sharpe"], n["rep"], n["active"]
    plateau = list(n["plateau"])
    g7 = [g7_part(p) for p in n["g7"].values()]
    return {
        "E1": T.rank_holds(n["e1"]["rank_p"]),
        "E2": T.e2_holds(n["e2"]["d"], n["e2"]["p"]),
        "E3": T.e3_holds(*n["e3"]["S"], *n["e3"]["X"]),
        "E4": bool(n["e4"]["S_2x"] > n["e4"]["N0_2x"]),
        "E6": bool(n["e6"]["holds"]),
        "E7": T.boom_holds([removal_items(r) for r in n["e7"]], T.E7_ITEMS),
        "P": bool(n["P"]["holds"]),
        "G1": S.point(rep["oos_sharpe_annual"] >= 1.0, rep["oos_sharpe_annual"]),
        "G2": S.point(n["e4"]["S_2x"] > 0.5, n["e4"]["S_2x"]),
        "G3": S.point(
            rep["dsr_effective_count"] >= T.DSR_MIN and act["dsr_effective"] >= T.DSR_MIN,
            rep["dsr_effective_count"],
            act["dsr_effective"],
        ),
        "G4": S.point(
            rep["pbo_mean"] <= T.PBO_MAX and act["pbo_mean"] <= T.PBO_MAX, rep["pbo_mean"], act["pbo_mean"]
        ),
        "G5(a)": S.point(T.keeps_share(sh, plateau), sh, *plateau),
        "G6": S.point(T.g6_holds(n["g6"]["p5"], budget), n["g6"]["p5"]),
        "G7": None if None in g7 else all(g7),
        "G8-excess": T.g8_excess_pass(n["g8"]["split"]),
    }


def point_value(item: str, nums, *, sharpe_s: float, budget):
    """One measurement point's outcome from its numbers (section 10): G1 >= 1.0; G2 > 0.5 (at 2x); G3 >= 0.95; G4
    <= 0.25; G5 keeps >= 0.7 x Sharpe(S) and Sharpe(S) > 0; G6 p5 >= -budget; G7 above B1 and B2; G8-excess on the
    split against its own N0; R1 a mean <= 2 orders a 30 days and at most 5 in any 30 days; the S(s_k) check's E1 on
    its rank p and E2 on D and p."""
    if item == "G1":
        return S.point(nums[0] >= 1.0, *nums)
    if item == "G2":
        return S.point(nums[0] > 0.5, *nums)
    if item == "G3":
        return S.point(nums[0] >= T.DSR_MIN, *nums)
    if item == "G4":
        return S.point(nums[0] <= T.PBO_MAX, *nums)
    if item == "G5":
        return S.point(T.keeps_share(sharpe_s, nums), sharpe_s, *nums)
    if item == "G6":
        return S.point(T.g6_holds(nums[0], budget), *nums)
    if item == "G7":
        return g7_part(nums)
    if item == "G8-excess":
        return T.g8_excess_pass(nums)
    if item == "R1":
        return S.point(nums["mean"] <= T.R1_MEAN and nums["most"] <= T.R1_MOST, nums["mean"])
    if item == "S(s_k) check" and len(nums) == 1:
        return S.point(T.rank_holds(nums[0]), *nums)
    if item == "S(s_k) check":
        return S.point(T.e2_holds(*nums), *nums)
    raise ValueError(f"point_value: no rule for {item!r}")


def e5b_holds(sharpe_s: float, weekdays: Mapping) -> bool:
    """E5(b): S re-run with each of the other 6 check weekdays keeps >= 0.7 x Sharpe(S), and Sharpe(S) > 0."""
    return T.keeps_share(sharpe_s, [weekdays[str(d)]["sharpe"] for d in S.CHECK_DAYS])


def train_criteria(a: Mapping, b: Mapping, weekdays: Mapping, e8: Mapping) -> tuple[dict, dict]:
    """E1-E8 and P (section 11) from seed A's and seed B's records at S, the weekdays and the Binance numbers."""
    e5a = T.e5a_holds(a["items"], b["items"], a["sharpe"], b["sharpe"])
    items = a["items"]
    criteria = {
        **{k: items[k] for k in ("E1", "E2", "E3", "E4")},
        "E5": bool(e5a["holds"] and e5b_holds(a["sharpe"], weekdays)),
        "E6": items["E6"],
        "E7": items["E7"],
        "E8": bool(T.rank_holds(e8["e1"]["rank_p"]) and T.e2_holds(e8["e2"]["d"], e8["e2"]["p"])),
        "P": items["P"],
    }
    return criteria, e5a


def at_s(ctx, label: str, b: dict, ev: Evaluations, settings) -> dict:
    """Everything sections 10 and 11 measure at one seed's S (Kraken)."""
    windows, limits = ctx["windows"], ctx["limits"]
    s, n0, x = b["S"], b["N0"], b["X"]
    e1_res = S.e1(b)
    e2_res = e2(ctx, s, n0)
    dd_s, p5_s, dd_x, p5_x = S.drawdown_of(s), S.g6_of(s), S.drawdown_of(x), S.g6_of(x)
    e4 = [S.sharpe(b["S2"]), S.sharpe(b["N0_2"])]
    loyo = T.loyo(s, n0)
    removals = e7_removals(ctx, b)
    power = V.power_count([r.attrs["share"] for r in b["runs"]], windows, ctx["K"].index)
    rep = overfitting_report(
        {
            "oos_returns": s,
            "wf_efficiency": ctx["wf"][label]["wf_efficiency"],
            "studies": ctx["studies"],
            "total_trials": ctx["n_raw"],
        },
        ctx["train"],
    )
    if rep["mc_drawdown_worst5pct"] != p5_s:
        raise S.Stop(f"seed {label}: G6's statistic is not overfitting_report's mc_drawdown_worst5pct")
    active = T.active_report(
        ctx["studies"],
        ctx["train"],
        first_row=V.FIRST_ACTIVE_ROW,
        oos_returns=s.to_numpy(),
        n_raw=ctx["n_raw"],
        n_strict=ctx["n_strict"],
    )
    full = T.active_report(
        ctx["studies"], ctx["train"], first_row=0, oos_returns=s.to_numpy(), n_raw=ctx["n_raw"]
    )
    for key, rep_key in (
        ("dsr_effective", "dsr_effective_count"),
        ("dsr_raw", "dsr_raw_count"),
        ("pbo_mean", "pbo_mean"),
    ):
        if not (full[key] == rep[rep_key] or (math.isnan(full[key]) and math.isnan(rep[rep_key]))):
            raise S.Stop(f"seed {label}: the active-row report at row 0 is not overfitting_report ({key})")
    sharpe_s = S.sharpe(s)
    plateau = []
    for step in V.plateau_steps(b["params"], limits):
        runs = [ctx["fn1"](p, piece) for p, piece in zip(step["params"], b["slices"], strict=True)]
        ctx["tally"].add("rule", len(runs))
        r = S.stitch(runs, windows)
        sh = S.sharpe(r)
        name = f"{step['param']} x{step['factor']:g}"
        ev.add(
            "plateau",
            label,
            "stitched",
            S.SOURCE,
            1,
            step["params"],
            S.series_metrics(r),
            counted=True,
            step=name,
            mark=step["mark"],
        )
        plateau.append(
            {
                "step": name,
                "mark": step["mark"],
                "marks": step["marks"],
                "params": step["params"],
                "sharpe": sh,
                "ratio": sh / sharpe_s if sharpe_s else math.nan,
                "series": r,
            }
        )
    g7 = g7_parts(ctx, s)
    g8_res = g8(ctx, s, n0)
    budget = ctx["budget"]
    numbers = {
        "sharpe": sharpe_s,
        "e1": S.e1_numbers(e1_res),
        "e2": S.e2_numbers(e2_res),
        "e3": {"S": [dd_s, p5_s], "X": [dd_x, p5_x]},
        "e4": {"S_2x": e4[0], "N0_2x": e4[1]},
        "e6": loyo,
        "e7": removals,
        "P": power,
        "rep": {k: rep[k] for k in ("oos_sharpe_annual", "dsr_effective_count", "pbo_mean")},
        "active": {k: active[k] for k in ("dsr_effective", "pbo_mean")},
        "plateau": [p["sharpe"] for p in plateau],
        "g6": {"p5": p5_s, "budget": budget},
        "g7": g7,
        "g8": {"split": g8_res["split"]},
    }
    items = s_items(numbers, budget)
    log = kept_log(b["runs"], windows)
    return {
        "items": items,
        "numbers": numbers,
        "sharpe": sharpe_s,
        "e1": S.e1_numbers(e1_res),
        "e2": S.e2_numbers(e2_res),
        "e3": {"S": [dd_s, p5_s], "X": [dd_x, p5_x], "x_info": b["x_info"]},
        "e4": {"S_2x": e4[0], "N0_2x": e4[1]},
        "e6": loyo,
        "e7": removals,
        "boom_years": ctx["years"],
        "P": power,
        "rep": rep,
        "active": {k: v for k, v in active.items() if k not in ("trial_sharpes", "logits_per_study")},
        "plateau": [{k: v for k, v in p.items() if k != "series"} for p in plateau],
        "plateau_series": [p["series"] for p in plateau],
        "g6": {"p5": p5_s, "budget": budget},
        "g7": g7,
        "g8": g8_res,
        "R1": {**r1(ctx, log), "order_hash": [r.attrs["order_hash"] for r in b["runs"]]},
        "log": log,
    }


# --------------------------------------------------------------------------------- the descriptions


def share_changes(share: np.ndarray, p0: int, last: int) -> int:
    """Share changes at closes p0 .. last - 1 (orders filled in the kept rows), the first buy included (a
    description; P is volsteady.power_count)."""
    prev = np.concatenate([[0.0], share[:-1]])
    rows = np.flatnonzero(share != prev)
    return int(sum(1 for t in rows.tolist() if p0 <= t <= last - 1))


def run_stats(results, windows, limits) -> list[dict]:
    """Per fold: share changes, limit fixes, orders, most orders in 30 days, days with crypto and at each q, turnover,
    costs, return, max drawdown and worst day, over the kept rows."""
    out = []
    for i, (r, w) in enumerate(zip(results, windows, strict=True)):
        log = T.order_log(r, w.t0)
        kept = S.plain(r.loc[w.t0 :].iloc[1:])
        p0 = r.index.get_loc(w.t0)
        q = r.attrs["q"][p0 + 1 :]
        out.append(
            {
                "fold": i,
                **result_metrics(r, w.t0),
                "share_changes": share_changes(r.attrs["share"], p0, len(r) - 1),
                "limit_fixes": int((log["reason"] == "limit").sum()),
                "orders": len(log),
                "most_orders_30d": int(T.rolling_order_count(log, kept.index).max(initial=0)),
                "days_with_crypto": float(np.mean((kept["w_BTC"] + kept["w_ETH"]).to_numpy() > 0.0)),
                "days_at_q": {f"{x:g}": float(np.mean(q == x)) for x in V.QUARTERS},
                "mean_q": float(np.mean(q)),
                "overshoot": S.overshoot(kept["w_BTC"], kept["w_ETH"], limits),
            }
        )
    return out


def fold_rows(results, windows) -> pd.DataFrame:
    return pd.concat([S.plain(r.loc[w.t0 : w.last].iloc[1:]) for r, w in zip(results, windows, strict=True)])


def kept_q(results, windows) -> np.ndarray:
    """The q in force at each kept close of the fold runs, stitched (INTERPRETATIONS["r3"])."""
    return np.concatenate(
        [
            r.attrs["q"][r.index.get_loc(w.t0) + 1 : r.index.get_loc(w.last) + 1]
            for r, w in zip(results, windows, strict=True)
        ]
    )


def risk_of_folds(ctx, b: dict, log: pd.DataFrame) -> dict:
    return S.r2_r5(
        ctx["limits"], fold_rows(b["runs"], ctx["windows"]), log, kept_q(b["runs"], ctx["windows"])
    )


def risk_of_fixed(ctx, run: pd.DataFrame) -> dict:
    kept = ctx["kept"]
    q = run.attrs["q"][run.index.get_indexer(kept)]
    return S.r2_r5(ctx["limits"], S.plain(run.loc[kept]), S.fixed_log(run, kept), q)


def kept_trades(res: pd.DataFrame, t0) -> np.ndarray:
    tr = np.asarray(res.attrs["trade_returns"], dtype=float)
    fill_rows = np.flatnonzero(res["turnover"].to_numpy() > 0)
    if len(tr) != len(fill_rows):
        raise S.Stop("trade_returns does not have one entry per fill row")
    return tr[res.index[fill_rows] > pd.Timestamp(t0)]


def counted_changes(share: np.ndarray, p0: int, last: int) -> list[int]:
    """P's counted share changes of one fold run (volsteady.power_count): rows p0 .. last - 1, the first buy out."""
    prev = np.concatenate([[0.0], share[:-1]])
    rows = np.flatnonzero(share != prev)
    return [t for t in rows[1:].tolist() if p0 <= t <= last - 1]


def episodes(ctx, b: dict) -> dict:
    """The episode table (INTERPRETATIONS["episodes"], ["whipsaw"])."""
    spells, whipsaws, changes = [], [], 0
    orders = {}  # (fold, fill bar) -> the order's cost: an order shared by two whipsaws is counted once (#60)
    for i, (r, w) in enumerate(zip(b["runs"], ctx["windows"], strict=True)):
        p0 = r.index.get_loc(w.t0)
        start = p0 + 1
        q, share = r.attrs["q"], r.attrs["share"]
        cb = ctx["K"][("BTC", "close")].loc[r.index].to_numpy(dtype=float)
        ce = ctx["K"][("ETH", "close")].loc[r.index].to_numpy(dtype=float)
        n0 = np.log1p(S.kept_of(b["n0_runs"][i], w.t0).to_numpy())
        sv = np.log1p(S.kept_of(r, w.t0).to_numpy())
        fills = r.attrs["fills"]
        t = start
        while t < len(r):
            if q[t] < 1.0:
                u = t
                while u + 1 < len(r) and q[u + 1] < 1.0:
                    u += 1
                growth = np.prod(
                    1.0
                    + 0.5 * (cb[t : u + 1] / cb[t - 1 : u] - 1.0)
                    + 0.5 * (ce[t : u + 1] / ce[t - 1 : u] - 1.0)
                )
                spells.append(
                    {
                        "fold": i,
                        "first": r.index[t].isoformat(),
                        "last": r.index[u].isoformat(),
                        "lowest_q": float(q[t : u + 1].min()),
                        "basket_return": float(growth - 1.0),
                        "regret": math.fsum(
                            (n0[t - start : u - start + 1] - sv[t - start : u - start + 1]).tolist()
                        ),
                    }
                )
                t = u + 1
            else:
                t += 1
        counted = counted_changes(share, p0, len(r) - 1)
        changes += len(counted)
        for c, d in zip(counted, counted[1:], strict=False):
            if share[d] == share[c - 1] and (r.index[d] - r.index[c]) <= pd.Timedelta(days=S.WHIPSAW_DAYS):
                for bar in (c + 1, d + 1):
                    orders[(i, bar)] = float(fills.loc[fills["bar"] == bar, "cost"].sum())
                cost = float(fills.loc[fills["bar"].isin([c + 1, d + 1]), "cost"].sum())
                whipsaws.append(
                    {
                        "fold": i,
                        "first": r.index[c].isoformat(),
                        "reversed": r.index[d].isoformat(),
                        "cost_usd": cost,
                    }
                )
    return {
        "step_back_spells": spells,
        "whipsaws": {
            "count": len(whipsaws),
            "share": len(whipsaws) / changes if changes else math.nan,
            "orders": len(orders),
            "cost_usd": math.fsum(orders.values()),
            "list": whipsaws,
        },
    }


def active_rescoring(ctx, studies, choices: dict) -> dict:
    """INTERPRETATIONS["active_rescoring"]: would each study's choice move on its active rows?"""
    out = {}
    for study in studies:
        trials = S.trial_table(ctx["train"], [study])
        done = trials[trials["state"] == "COMPLETE"].copy()
        if done.empty:
            out[study] = None
            continue
        m = load_trial_returns(study, ctx["train"])
        scores = []
        for _, row in done.iterrows():
            r = m[f"t{int(row['number'])}"].to_numpy(dtype=float)[V.FIRST_ACTIVE_ROW :]
            blocks = [stats.annualized_sharpe(x, 365) for x in np.array_split(r, 4)]
            score = float(np.mean(blocks) - 0.5 * np.std(blocks))
            scores.append(-10.0 if row["n_trades"] < 5 else score)
        rescored = done.assign(value=scores)
        old = stable_region(done, list(V.SPECS), k=S.STABLE_K)
        new = stable_region(rescored, list(V.SPECS), k=S.STABLE_K)
        out[study] = {
            "chosen": old["trial_number"],
            "rescored": new["trial_number"],
            "moves": old["trial_number"] != new["trial_number"],
            "unit_distance": S.unit_distance(S.plain_params(old["params"]), S.plain_params(new["params"])),
        }
    return out


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


def r4(ctx, theta: dict, base: pd.DataFrame, ev: Evaluations) -> dict:
    """R4: theta_final(A) at the other book sizes (counted cost variants; their orders must be theta's)."""
    kept, years = ctx["kept"], ctx["covered"] / 365.0
    out = {}
    for book in S.R4_BOOKS:
        if book == S.REF_BOOK:
            res, costs = base, ctx["costs1"]
        else:
            costs = S.costs_for(ctx["config_dir"], book)
            res = V.vol_backtest(theta, ctx["K"], limits=ctx["limits"], costs=costs)
            ctx["tally"].add("rule")
            if res.attrs["order_hash"] != base.attrs["order_hash"]:
                raise S.Stop(f"stop rule 13: theta_final(A) at a USD {book:,.0f} book orders differently")
            ev.add(
                "R4",
                "A",
                "all",
                S.SOURCE,
                1,
                {**theta, "book_usd": book},
                kept_metrics(res, kept),
                counted=True,
            )
        rows = res.loc[kept]
        fills = res.attrs["fills"]
        legs = fills[fills["ts"].isin(kept)]
        gas = costs.gas_usd_per_trade
        fee_fraction = 0.0
        for t, g in legs.groupby("bar"):
            paid = float(g["cost"].sum())
            fee_fraction += float(res["cost"].iloc[int(t)]) * (paid - gas * len(g)) / paid if paid else 0.0
        sh = S.sharpe(rows["ret"])
        out[str(int(book))] = {
            "customer_fees_pct_a_year": 100.0 * fee_fraction / years,
            "gas_usd_a_year": gas * len(legs) / years,
            "sharpe_with_gas": sh,
        }
    ref = out[str(int(S.REF_BOOK))]["sharpe_with_gas"]
    keeps = [b for b in S.R4_BOOKS if out[str(int(b))]["sharpe_with_gas"] >= 0.9 * ref]
    out["min_wallet_usd_keeping_90pct"] = min(keeps) if ref > 0 and keeps else None
    return out


# --------------------------------------------------------------------------------- the train phase


def searches(ctx: dict, k: int, context: dict, settings, finals: dict) -> None:
    """Section 7: per seed, the 5 walk-forward studies and the final study on all train rows (seed + 5000)."""
    for label, seed in S.SEEDS.items():
        tag = S.study_tag(seed, k)
        cfg = S.search_config(seed, settings)
        t = time.time()
        ctx["wf"][label] = walk_forward_optimize(
            tag,
            ctx["fn1"],
            list(V.SPECS),
            ctx["K"],
            ctx["folds"],
            ctx["train"],
            cfg,
            warmup=T.WARMUP,
            context={**context, "seed": seed},
        )
        final_name = f"{tag}_final"
        trials = run_study(
            final_name,
            ctx["fn1"],
            list(V.SPECS),
            ctx["K"],
            ctx["train"],
            replace(cfg, seed=seed + S.FINAL_SEED_OFFSET),
            {**context, "seed": seed},
        )
        finals[label] = {"study": final_name, "choice": stable_region(trials, list(V.SPECS), k=S.STABLE_K)}
        print(
            f"seed {label}: 6 studies in {time.time() - t:.1f}s, OOS Sharpe {ctx['wf'][label]['oos_sharpe']:.3f}",
            flush=True,
        )


def theta_in_sample(ctx, choice: dict, final_name: str, label: str) -> pd.DataFrame:
    """theta_final as one fixed configuration over the train panel: the final study's own trial, re-run; it must
    reproduce its logged returns."""
    theta = S.plain_params(choice["params"])
    res = ctx["fn1"](theta, ctx["K"])
    ctx["tally"].add("rule")
    logged = pd.read_parquet(
        ctx["train"] / final_name / "returns" / f"trial_{choice['trial_number']:06d}.parquet"
    )
    col = logged.iloc[:, 0]
    if not (col.index.equals(res.index) and np.array_equal(col.to_numpy(), res["ret"].to_numpy())):
        raise S.Stop(f"theta_final({label}) re-run does not reproduce its logged trial returns")
    return res


def load_panels(args, summary, run_dir, ctx) -> dict:
    start = summary["start"]
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
        panels[source] = panel
    summary["panels"] = {s: S.panel_record(p) for s, p in panels.items()}
    summary["status"] = "panels loaded"
    S.write_json(run_dir / "summary.json", summary)
    for source, panel in panels.items():
        if len(panel) != S.ROWS["train"][source]:
            raise S.Stop(
                f"stop rule 2: {source} has {len(panel)} train rows, the plan counts {S.ROWS['train'][source]}"
            )
        if panel.attrs["snapshot_id"] != start["snapshot"]["snapshot_id"]:
            raise S.Stop(
                f"stop rule 2: {source}: snapshot {panel.attrs['snapshot_id']} is not the one SNAPSHOT.json names"
            )
        if start["data"] == "real" and summary["panels"][source]["hash"] != S.PANEL_SHA256[source]:
            raise S.Stop(
                f"stop rule 2: the {source} train panel does not hash to {S.PANEL_SHA256[source]} (section 3)"
            )
    return panels


def train_phase(args, summary: dict, run_dir: Path, ctx: dict, settings) -> dict:
    """Load the train panels and run everything; returns the results."""
    start, train, k = summary["start"], ctx["train"], summary["run"]
    panels = load_panels(args, summary, run_dir, ctx)
    K, Bn = panels[S.SOURCE], panels[S.ROBUSTNESS]
    print(f"panels: Kraken {len(K)} rows, Binance {len(Bn)} rows (train)", flush=True)
    folds = walk_forward(len(K), train_size=T.FOLD_ROWS, test_size=T.FOLD_ROWS, expanding=True)
    windows = S.windows_of(K.index)
    ctx.update(K=K, Bn=Bn, folds=folds, windows=windows, wf={})
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
        "branch": start["branch"]["branch"],
        "min_cash": start["risk_limits"]["min_cash"],
        "max_coin": start["risk_limits"]["max_coin"],
        "max_drawdown_budget_pct": S.jsonable(start["risk_limits"]["max_drawdown_budget_pct"]),
        "risk_levels_sha256": start["risk_limits"]["sha256"],
        "label": S.LABEL,
    }
    finals: dict = {}
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
    n_raw = len(trials_all)
    ctx.update(studies=studies, n_raw=n_raw, n_strict=n_raw + S.STRICT_EXTRA)
    ev = Evaluations(k)
    ctx["ev"] = ev
    limits, c1, c2, tally = ctx["limits"], ctx["costs1"], ctx["costs2"], ctx["tally"]

    # ---- S for both seeds, with R_0, the shifts, N0 and X (section 9)
    bundles, items = {}, {}
    for label in S.SEEDS:
        wf = ctx["wf"][label]
        params = [
            S.plain_params({n: wf["folds"].iloc[i][f"p_{n}"] for n in V.PARAM_NAMES})
            for i in range(len(windows))
        ]
        b = S.plain_bundle(
            K,
            windows,
            params,
            limits=limits,
            costs1=c1,
            costs2=c2,
            offsets="all",
            tally=tally,
            what=f"seed {label} S",
        )
        if b["W"] != S.W_KRAKEN or len(b["S"]) != S.KEPT_ROWS:
            raise S.Stop(
                f"seed {label}: {b['W']} check closes and {len(b['S'])} kept rows; the plan counts 260 and 1820"
            )
        if not (
            b["S"].index.equals(wf["oos_returns"].index)
            and np.array_equal(b["S"].to_numpy(), wf["oos_returns"].to_numpy())
        ):
            raise S.Stop(
                f"seed {label}: H0 does not reproduce walk_forward_optimize's oos_returns bit for bit"
            )
        for i, (r, w) in enumerate(zip(b["runs"], windows, strict=True)):
            if sd.kept_fills(r, w.t0) != int(wf["folds"].iloc[i]["oos_trades"]):
                raise S.Stop(
                    f"seed {label} fold {i}: kept fills differ from walk_forward_optimize's oos_trades"
                )
        bundles[label] = b
        log_bundle(ev, b, "S", label, S.SOURCE, windows)
        log_bundle(
            ev,
            {**b, "runs": b["runs2"], "S": b["S2"]},
            "S_2x",
            label,
            S.SOURCE,
            windows,
            counted=True,
            cost_x=2,
        )
        log_shifts(ev, "shift", label, S.SOURCE, {u: r for u, r in b["shifts"].items() if u > T.LEAD_GUARD})
        log_shifts(ev, "lead", label, S.SOURCE, {u: r for u, r in b["shifts"].items() if u <= T.LEAD_GUARD})
        for name in ("R0", "N0", "N0_2", "X"):
            ev.add(
                name,
                label,
                "stitched",
                S.SOURCE,
                2 if name.endswith("_2") else 1,
                None,
                S.series_metrics(b[name]),
            )
    kept = bundles["A"]["S"].index
    if not bundles["B"]["S"].index.equals(kept):
        raise S.Stop("the two seeds' kept rows differ")
    btc = K[("BTC", "close")]
    years = T.boom_years(btc, kept)
    b1 = pd.concat([S.kept_of(sd.buy_and_hold_b1(K, w, c1), w.t0) for w in windows])
    b2 = pd.concat([S.kept_of(sd.fifty_fifty_b2(K, w, c1), w.t0) for w in windows])
    tally.add("comparator", 2 * len(windows))
    ev.add("B1", "", "stitched", S.SOURCE, 1, {"weight": 1.0}, S.series_metrics(b1))
    ev.add("B2", "", "stitched", S.SOURCE, 1, {"weight": 0.5, "every": 30}, S.series_metrics(b2))
    ctx.update(
        kept=kept,
        covered=T.covered_days(K.index, kept),
        years=years,
        table=sd.regime_table(btc, kept),
        B1=b1,
        B2=b2,
        g7_masks={
            "full": np.ones(len(kept), dtype=bool),
            "without the best bar-year": T.without_years(kept, years[:1]),
            "without the two best bar-years": T.without_years(kept, years[:2]),
        },
    )
    for label in S.SEEDS:
        items[label] = at_s(ctx, label, bundles[label], ev, settings)
    a_b, a_i = bundles["A"], items["A"]
    ctx.update(trial_sharpes=sd.report_trial_sharpes(studies, train), n_eff=a_i["rep"]["trials_effective"])

    # ---- theta_final, the default and the grid (section 8)
    theta = {lab: theta_in_sample(ctx, finals[lab]["choice"], finals[lab]["study"], lab) for lab in S.SEEDS}
    theta_params = {lab: S.plain_params(finals[lab]["choice"]["params"]) for lab in S.SEEDS}
    for lab in S.SEEDS:
        ev.add(
            "theta_final_in_sample",
            lab,
            "all",
            S.SOURCE,
            1,
            theta_params[lab],
            kept_metrics(theta[lab], kept),
        )
    theta2 = V.vol_backtest(theta_params["A"], K, limits=limits, costs=c2)
    tally.add("rule")
    if theta2.attrs["order_hash"] != theta["A"].attrs["order_hash"]:
        raise S.Stop("stop rule 13: theta_final(A) orders differently at 2x")
    ev.add("theta_final_2x_check", "A", "all", S.SOURCE, 2, theta_params["A"], kept_metrics(theta2, kept))
    default = T.default_share(theta_params["A"]["crypto_share"])
    grid = {}
    for s_k in T.ALLOWED_S:
        p = S.with_share(theta_params["A"], s_k)
        run1 = ctx["fn1"](p, K)
        run2 = ctx["fn2"](p, K)
        tally.add("rule", 2)
        if run1.attrs["order_hash"] != run2.attrs["order_hash"]:
            raise S.Stop(f"stop rule 13: grid step s = {s_k:.2f} orders differently at 2x")
        series, series2 = S.on_kept(run1, kept), S.on_kept(run2, kept)
        n0 = S.fixed_n0(K, run1, windows, s_k, limits=limits, costs=c1)
        tally.add("comparator", len(windows))
        ev.add("grid", "A", "all", S.SOURCE, 1, p, kept_metrics(run1, kept), counted=True)
        ev.add("grid_2x", "A", "all", S.SOURCE, 2, p, kept_metrics(run2, kept), counted=True)
        ev.add("grid_N0", "A", "stitched", S.SOURCE, 1, p, S.series_metrics(n0))
        sh, sh2, p5 = S.sharpe(series), S.sharpe(series2), S.g6_of(series)
        grid[s_k] = {
            "params": p,
            "run": run1,
            "series": series,
            "sharpe": sh,
            "sharpe_2x": sh2,
            "p5": p5,
            "drawdown": S.drawdown_of(series),
            "g7": g7_parts(ctx, series),
            "g8": g8(ctx, series, n0),
            "R1": fixed_r1(ctx, run1),
            "n0": n0,
        }
    g5b = []
    for step in V.plateau_steps([S.with_share(theta_params["A"], default)], limits):
        res = ctx["fn1"](step["params"][0], K)
        tally.add("rule")
        r = S.on_kept(res, kept)
        name = f"{step['param']} x{step['factor']:g}"
        ev.add(
            "plateau_default",
            "A",
            "all",
            S.SOURCE,
            1,
            step["params"][0],
            S.series_metrics(r),
            counted=True,
            step=name,
        )
        g5b.append({"step": name, "mark": step["mark"], "params": step["params"][0], "sharpe": S.sharpe(r)})

    # ---- S(s_k): the walk-forward with each fold's s replaced (section 8)
    sk = {}
    for s_k in T.ALLOWED_S:
        params_k = [S.with_share(p, s_k) for p in a_b["params"]]
        bk = S.plain_bundle(
            K,
            windows,
            params_k,
            limits=limits,
            costs1=c1,
            costs2=c2,
            offsets="guarded",
            x=False,
            tally=tally,
            what=f"S({s_k:.2f})",
        )
        log_bundle(ev, bk, "S_sk", "A", S.SOURCE, windows, counted=True, share=s_k)
        ev.add(
            "S_sk_2x",
            "A",
            "stitched",
            S.SOURCE,
            2,
            params_k,
            S.series_metrics(bk["S2"]),
            counted=True,
            share=s_k,
        )
        log_shifts(ev, "shift_sk", "A", S.SOURCE, bk["shifts"], share=s_k)
        ev.add("N0_sk", "A", "stitched", S.SOURCE, 1, None, S.series_metrics(bk["N0"]), share=s_k)
        e1_k = S.e1(bk)
        e2_k = e2(ctx, bk["S"], bk["N0"])
        sk[s_k] = {
            "bundle": bk,
            "sharpe": S.sharpe(bk["S"]),
            "sharpe_2x": S.sharpe(bk["S2"]),
            "p5": S.g6_of(bk["S"]),
            "drawdown": S.drawdown_of(bk["S"]),
            "e1": S.e1_numbers(e1_k),
            "e2": S.e2_numbers(e2_k),
        }

    # ---- E5(b), the daily-check description, Binance (E8)
    weekdays = {}
    for day in (*S.CHECK_DAYS, None):
        fn = partial(V.vol_backtest, limits=limits, costs=c1, weekday=day)
        runs = [fn(p, piece) for p, piece in zip(a_b["params"], a_b["slices"], strict=True)]
        tally.add("rule", len(runs))
        r = S.stitch(runs, windows)
        name = "daily" if day is None else str(day)
        ev.add(
            "check_day",
            "A",
            "stitched",
            S.SOURCE,
            1,
            a_b["params"],
            S.series_metrics(r),
            counted=True,
            weekday=name,
        )
        weekdays[name] = {
            "sharpe": S.sharpe(r),
            "orders": int(sum(len(T.order_log(x, w.t0)) for x, w in zip(runs, windows, strict=True))),
        }
    e5b = e5b_holds(a_i["sharpe"], weekdays)
    bw = windows[1:]
    bn = S.plain_bundle(
        Bn,
        bw,
        a_b["params"][1:],
        limits=limits,
        costs1=c1,
        costs2=None,
        like=K,
        offsets="guarded",
        x=False,
        tally=tally,
        what="Binance S",
    )
    if bn["W"] != S.W_BINANCE or not bn["S"].index.equals(kept[kept > windows[1].t0]):
        raise S.Stop(f"Binance: {bn['W']} check closes, or kept rows not Kraken's folds 1-4 (section 3)")
    log_bundle(ev, bn, "S", "A", S.ROBUSTNESS, bw, counted=True)
    log_shifts(ev, "shift", "A", S.ROBUSTNESS, bn["shifts"])
    ev.add("N0", "A", "stitched", S.ROBUSTNESS, 1, None, S.series_metrics(bn["N0"]))
    e8_e1 = S.e1(bn)
    e8_e2 = e2(ctx, bn["S"], bn["N0"])
    e8_numbers = {"e1": S.e1_numbers(e8_e1), "e2": S.e2_numbers(e8_e2)}
    criteria, e5a = train_criteria(items["A"], items["B"], weekdays, e8_numbers)
    verdict = V.verdict(criteria, changes=a_i["P"]["total"])

    # ---- the measurement points of section 10 and the headline
    theta_r1 = fixed_r1(ctx, theta["A"])
    points, point_nums = measurement_points(ctx, a_i, theta_r1, grid, default, g5b, sk)
    head = V.headline(verdict, points)
    narrow = narrowing_line(ctx, points, grid, sk, default)

    # ---- descriptions, counts and outputs (no stop-loss variant: section 11A)
    descriptions = describe(ctx, bundles, items, theta, theta_params, grid, default, weekdays, bn, sk, finals)
    evals = ev.frame()
    counted = check_counted(evals)
    out_files(args, ctx, run_dir, bundles, items, grid, sk, bn, evals, trials_all)
    failed = trials_all[failed_rows]
    earlier = earlier_runs(train, k)
    own = {
        "verdict": verdict["label"],
        "headline": head["headline"],
        "look_earned": verdict["look_earned"],
        "e1_rank_p": a_i["e1"]["rank_p"],
        "e2_p": a_i["e2"]["p"],
    }
    reported = reported_block(train, k, own, start)
    return {
        "label": S.LABEL,
        "verdict": verdict,
        "headline": head,
        "criteria": criteria,
        "points": [
            {"item": i, "point": p, "value": v, "numbers": point_nums[(i, p)]} for (i, p), v in points.items()
        ],
        "gates": gate_summary(points),
        "narrowing": narrow,
        "own": own,
        "reported": reported,
        "pending": pending(reported),
        "seeds": {lab: seed_record(bundles[lab], items[lab], windows) for lab in S.SEEDS},
        "e5": {"a": e5a, "b": {"holds": e5b, "weekdays": weekdays, "sharpe_S": a_i["sharpe"]}},
        "e8": {
            "e1": S.e1_numbers(e8_e1),
            "e2": S.e2_numbers(e8_e2),
            "sharpe": S.sharpe(bn["S"]),
            "sharpe_n0": S.sharpe(bn["N0"]),
            "kraken_folds_1_4": {
                "sharpe": S.sharpe(a_b["S"].loc[bn["S"].index]),
                "sharpe_n0": S.sharpe(a_b["N0"].loc[bn["S"].index]),
                "d": S.sharpe(a_b["S"].loc[bn["S"].index]) - S.sharpe(a_b["N0"].loc[bn["S"].index]),
            },
        },
        "theta_final": {
            lab: {
                "study": finals[lab]["study"],
                "trial_number": finals[lab]["choice"]["trial_number"],
                "params": theta_params[lab],
            }
            for lab in S.SEEDS
        },
        "default": {"share": default, "theta_share": theta_params["A"]["crypto_share"], "g5b": g5b},
        "grid": {
            f"{s:.2f}": {k2: v for k2, v in g.items() if k2 not in ("run", "series", "n0")}
            for s, g in grid.items()
        },
        "s_k": {f"{s:.2f}": {k2: v for k2, v in g.items() if k2 != "bundle"} for s, g in sk.items()},
        "descriptions": descriptions,
        "trials": {
            "n_raw": n_raw,
            "n_strict": ctx["n_strict"],
            "n_strict_k4_15": ctx["n_strict"] + S.K4_AS_15,
            "counted_runs": counted,
            "studies": studies,
            "this_run": int(this.sum()),
            "evaluations": len(evals),
            "minus_10_trials": {
                st: int(((trials_all["study"] == st) & (trials_all["value"] == -10.0)).sum())
                for st in studies
            },
        },
        "tally": tally.n,
        "pbo_per_study": pbo_table(studies, train),
        "failed_trials": S.jsonable(
            failed[
                ["study", "number", "state", "fail_reason", *(f"params_{n}" for n in V.PARAM_NAMES)]
            ].to_dict(orient="records")
        ),
        "failure_log": failure_log.records,
        "triage_required": bool(len(failed)),
        "earlier_runs": earlier,
    }


def measurement_points(ctx, a_i, theta_r1, grid, default, g5b, sk) -> tuple[dict, dict]:
    """Every point of TP 10's table "Where each gate and R1 is measured (Branch R)" (volsteady.measurement_points
    names them): the numbers it judges, and its outcome by :func:`point_value` (True, False or None, MISSING)."""
    n = a_i["numbers"]
    rep, act = n["rep"], n["active"]
    gname = {s: f"grid s={s:.2f}" for s in T.ALLOWED_S}
    kname = {s: f"S({s:.2f})" for s in T.ALLOWED_S}
    nums = {("G1", "S"): [rep["oos_sharpe_annual"]], ("G2", "S at 2x"): [n["e4"]["S_2x"]]}
    for s in T.ALLOWED_S:
        g, k = grid[s], sk[s]
        nums[("G1", gname[s])] = [g["sharpe"]]
        nums[("G1", kname[s])] = [k["sharpe"]]
        nums[("G2", f"{gname[s]} at 2x")] = [g["sharpe_2x"]]
        nums[("G2", f"{kname[s]} at 2x")] = [k["sharpe_2x"]]
        nums[("G5", f"(c) {gname[s]}")] = [g["sharpe"]]
        nums[("G6", gname[s])] = [g["p5"]]
        nums[("G6", kname[s])] = [k["p5"]]
        nums[("S(s_k) check", f"E1 at {kname[s]}")] = [k["e1"]["rank_p"]]
        nums[("S(s_k) check", f"E2 at {kname[s]}")] = [k["e2"]["d"], k["e2"]["p"]]
        nums[("G8-excess", gname[s])] = g["g8"]["split"]
        nums[("R1", gname[s])] = g["R1"]
    nums[("G3", "S (all rows)")] = [rep["dsr_effective_count"]]
    nums[("G3", "S (active rows)")] = [act["dsr_effective"]]
    nums[("G4", "search studies (all rows)")] = [rep["pbo_mean"]]
    nums[("G4", "search studies (active rows)")] = [act["pbo_mean"]]
    for p, sh in zip(a_i["plateau"], n["plateau"], strict=True):
        nums[("G5", f"(a) {p['step']}")] = [sh]
    for p in g5b:
        nums[("G5", f"(b) default {p['step']}")] = [p["sharpe"]]
    nums[("G6", "S")] = [n["g6"]["p5"]]
    suffixes = {
        "full": "",
        "without the best bar-year": " without the best bar-year",
        "without the two best bar-years": " without the two best bar-years",
    }
    for name, parts in (
        ("S", n["g7"]),
        ("default", grid[default]["g7"]),
        *((gname[s], grid[s]["g7"]) for s in T.ALLOWED_S),
    ):
        for key, suffix in suffixes.items():
            nums[("G7", f"{name}{suffix}")] = {k: parts[key][k] for k in ("sharpe", "B1", "B2")}
    nums[("G8-excess", "S")] = n["g8"]["split"]
    nums[("G8-excess", "default")] = grid[default]["g8"]["split"]
    nums[("R1", "S")] = a_i["R1"]
    nums[("R1", "theta_final(A)")] = theta_r1
    nums[("R1", "default")] = grid[default]["R1"]
    nums = check_points(nums)
    pts = {
        key: point_value(key[0], value, sharpe_s=n["sharpe"], budget=ctx["budget"])
        for key, value in nums.items()
    }
    return pts, nums


def check_points(pts: dict) -> dict:
    """The points must be exactly TP 10's table (volsteady.measurement_points), in its order; otherwise stop."""
    order = V.measurement_points()
    if set(pts) != set(order):
        raise S.Stop(
            f"the measurement points differ from section 10's table: {sorted(set(pts) ^ set(order))[:5]}"
        )
    return {key: pts[key] for key in order}


def check_counted(evals: pd.DataFrame) -> int:
    """The strict count's runs logged (INTERPRETATIONS["counted"]): 48 rows, K4 adding 1 that is not a run."""
    counted = int(evals["counted"].sum())
    need = S.STRICT_EXTRA - 1
    if counted != need:
        raise S.Stop(f"{counted} counted runs logged; the strict count needs {need} (+1 for K4)")
    return counted


def gate_summary(points: dict) -> dict:
    """Each item holds only if every point of its row holds (section 10): PASS, FAIL (some point fails) or MISSING
    (none fails, some is MISSING). G9: NOT RUN."""
    out = {}
    for (item, _), value in points.items():
        out.setdefault(item, []).append(value)
    table = {}
    for item, values in out.items():
        table[item] = (
            "PASS"
            if all(v is True for v in values)
            else ("FAIL" if any(v is False for v in values) else "MISSING")
        )
    table["G9"] = "NOT RUN"
    return table


def narrowing_line(ctx, points, grid, sk, default) -> dict:
    """Section 8's narrowing, reported next to the headline, never applied (INTERPRETATIONS["narrowing"])."""
    per = {s: [] for s in T.ALLOWED_S}
    global_other = False
    for (item, pt), value in points.items():
        if value is True:
            continue
        owner = next(
            (
                s
                for s in T.ALLOWED_S
                if pt.endswith(f"s={s:.2f}") or f"s={s:.2f} " in pt or f"S({s:.2f})" in pt
            ),
            None,
        )
        if item == "G5" and pt.startswith("(b)"):
            owner = default
        if item == "G7" and pt.startswith("default"):
            owner = default
        if item in ("G8-excess", "R1") and pt == "default":
            owner = default
        if owner is None:
            if not (item == "G6" and pt == "S"):
                global_other = True
            continue
        per[owner].append(item)
    values = {
        s: {
            "p5": min(grid[s]["p5"], sk[s]["p5"]),
            "risk_fail": "G6" in per[s],
            "other_fail": global_other or any(i != "G6" for i in per[s]),
        }
        for s in T.ALLOWED_S
    }
    return T.narrowing(values, default, ctx["budget"], g6_fails_at_s=points[("G6", "S")] is not True)


def seed_record(b: dict, it: dict, windows) -> dict:
    return {
        "params": b["params"],
        "sharpe": it["sharpe"],
        "items": it["items"],
        "e1": it["e1"],
        "e2": it["e2"],
        "e3": it["e3"],
        "e4": it["e4"],
        "e6": it["e6"],
        "e7": it["e7"],
        "boom_years": it["boom_years"],
        "P": it["P"],
        "overfitting_report": it["rep"],
        "active_report": it["active"],
        "plateau": it["plateau"],
        "g6": it["g6"],
        "g7": it["g7"],
        "g8": {
            "excess_pass": it["g8"]["excess_pass"],
            "literal_pass": it["g8"]["literal_pass"],
            "split": it["g8"]["split"],
        },
        "R1": it["R1"],
        "W": b["W"],
    }


def describe(ctx, bundles, items, theta, theta_params, grid, default, weekdays, bn, sk, finals) -> dict:
    """Section 16's descriptions (none decides)."""
    a_b, a_i, windows, kept = bundles["A"], items["A"], ctx["windows"], ctx["kept"]
    out = {}
    folds = []
    for lab in S.SEEDS:
        wf = ctx["wf"][lab]
        for i, st in enumerate(run_stats(bundles[lab]["runs"], windows, ctx["limits"])):
            fs = wf["folds"].iloc[i]
            folds.append(
                {
                    "seed": lab,
                    **st,
                    "params": bundles[lab]["params"][i],
                    "study": fs["study"],
                    "is_sharpe": fs["is_sharpe"],
                    "oos_sharpe": fs["oos_sharpe"],
                    "wf_efficiency": fs["oos_sharpe"] / fs["is_sharpe"] if fs["is_sharpe"] > 0 else math.nan,
                    "trials": int(fs["trials"]),
                    "neighbourhood": neighbourhood(
                        S.trial_table(ctx["train"], [fs["study"]]), bundles[lab]["params"][i]
                    ),
                }
            )
    out["folds"] = folds
    r0_run = a_b["R0_run"]
    boundary = [w.t0 for w in windows[1:]]
    s_turn = math.fsum(
        math.fsum(r["turnover"].loc[w.t0 :].iloc[1:].tolist())
        for r, w in zip(a_b["runs"], windows, strict=True)
    )
    out["r0_minus_s"] = {
        "turnover_R0_kept": float(r0_run["turnover"].loc[kept].sum()),
        "turnover_R0_boundaries": float(r0_run["turnover"].loc[boundary].sum()),
        "turnover_S_kept": s_turn,
        "difference": float(r0_run["turnover"].loc[kept].sum())
        + float(r0_run["turnover"].loc[boundary].sum())
        - s_turn,
    }
    span_n0 = T.from_t0(
        a_b["span"],
        r0_run.attrs["targets"],
        windows[0].t0,
        T.share_targets(a_b["params"][0]["crypto_share"]),
        limits=ctx["limits"],
        costs=ctx["costs1"],
    )
    ctx["tally"].add("comparator")
    ctx["N0_span"] = S.on_kept(span_n0, kept)
    lead = {u: r for u, r in a_b["shifts"].items() if u <= T.LEAD_GUARD}
    lag = {u: r for u, r in a_b["shifts"].items() if u >= a_b["W"] - T.LEAD_GUARD}
    sh_r0 = S.sharpe(a_b["R0"])
    out["stitched"] = {
        **{k: S.series_metrics(a_b[k]) for k in ("S", "R0", "N0", "X", "S2")},
        "B1": S.series_metrics(ctx["B1"]),
        "B2": S.series_metrics(ctx["B2"]),
        "N0_span": S.series_metrics(ctx["N0_span"]),
        "shifts": {
            **mc.percentiles([S.sharpe(r) for u, r in a_b["shifts"].items() if u > T.LEAD_GUARD]),
            "rank_p": a_i["e1"]["rank_p"],
        },
        "binance": S.series_metrics(bn["S"]),
        "folds_1_4": S.series_metrics(a_b["S"].loc[bn["S"].index]),
        "b3_lead": {
            **mc.percentiles([S.sharpe(r) for r in lead.values()]),
            "rank_p": (1 + sum(S.sharpe(r) >= sh_r0 for r in lead.values())) / (len(lead) + 1),
        },
        "r0_rank_among_lags": (1 + sum(S.sharpe(r) >= sh_r0 for r in lag.values())) / (len(lag) + 1),
    }
    out["trade_frequency"] = {
        "S": S.frequency(a_i["log"], kept, windows),
        "theta_final(A)": S.frequency(S.fixed_log(theta["A"], kept), kept, windows),
        "default": S.frequency(S.fixed_log(grid[default]["run"], kept), kept, windows),
        **{
            f"grid s={s:.2f}": S.frequency(S.fixed_log(g["run"], kept), kept, windows)
            for s, g in grid.items()
        },
    }
    # leave one year out, the boom years, the two bear years together
    loyo = {}
    for year in sorted(set(T.bar_years(kept).tolist())):
        mask = T.without_years(kept, [year])
        loyo[str(year)] = removal_row(ctx, a_b, a_i, mask)
    bears = T.without_years(kept, list(S.BEAR_YEARS))
    diff = np.log1p(a_b["S"].to_numpy()) - np.log1p(a_b["N0"].to_numpy())
    out["leave_one_year_out"] = loyo
    out["bear_years_removed"] = {
        "delta": math.fsum(diff[bears].tolist()),
        "D": S.sharpe(S.masked(a_b["S"], bears)) - S.sharpe(S.masked(a_b["N0"], bears)),
        "e1_rank_p": T.e1_test(a_b["R0"].to_numpy(), a_b["shifts"], a_b["W"], keep=bears)["rank_p"],
    }
    out["episodes"] = episodes(ctx, a_b)
    n_eff = a_i["rep"]["trials_effective"]
    s_np = a_b["S"].to_numpy()
    out["dsr"] = {
        "effective": a_i["rep"]["dsr_effective_count"],
        "raw": a_i["rep"]["dsr_raw_count"],
        "strict": stats.deflated_sharpe_ratio(s_np, ctx["trial_sharpes"], n_trials=ctx["n_strict"])["dsr"],
        "strict_k4_15": stats.deflated_sharpe_ratio(
            s_np, ctx["trial_sharpes"], n_trials=ctx["n_strict"] + S.K4_AS_15
        )["dsr"],
        "active": a_i["active"],
        "n_effective": n_eff,
        "n_raw": ctx["n_raw"],
        "n_strict": ctx["n_strict"],
    }
    trades = np.concatenate([kept_trades(r, w.t0) for r, w in zip(a_b["runs"], windows, strict=True)])
    turnover = pd.concat(
        [S.plain(r["turnover"].loc[w.t0 :].iloc[1:]) for r, w in zip(a_b["runs"], windows, strict=True)]
    )
    s_set = ctx["settings"]
    out["monte_carlo"] = {
        "block_20": mc.percentiles(
            mc.block_bootstrap_drawdowns(s_np, mean_block=20, n_sims=1000, seed=0), (5, 50)
        ),
        "block_60": mc.percentiles(
            mc.block_bootstrap_drawdowns(s_np, mean_block=60, n_sims=1000, seed=0), (5, 50)
        ),
        "shuffled_trades": {
            "periods": len(trades),
            **mc.percentiles(mc.shuffled_trade_drawdowns(trades, n_sims=s_set.shuffle_sims, seed=0), (5, 50)),
        },
        "degraded_execution": mc.percentiles(
            mc.degrade_execution(
                s_np, turnover.to_numpy(), extra_cost_bps=S.DEGRADE_BPS, n_sims=s_set.degrade_sims, seed=0
            )
        ),
    }
    fills = sum(sd.kept_fills(r, w.t0) for r, w in zip(a_b["runs"], windows, strict=True))
    out["trades_per_parameter"] = {
        "kept_fills": fills,
        "per_2": fills / 2,
        "per_3": fills / 3,
        "flag": fills / 2 < S.TRADES_FLAG,
    }
    out["daily_check"] = weekdays["daily"]
    out["weekdays"] = weekdays
    out["block_20_e2"] = S.e2_numbers(e2(ctx, a_b["S"], a_b["N0"], mean_block=20))
    out["active_rescoring"] = active_rescoring(ctx, ctx["studies"], finals)
    out["risk"] = {
        "S": risk_of_folds(ctx, a_b, a_i["log"]),
        "theta_final(A)": risk_of_fixed(ctx, theta["A"]),
        "default": risk_of_fixed(ctx, grid[default]["run"]),
        **{f"grid s={s:.2f}": risk_of_fixed(ctx, g["run"]) for s, g in grid.items()},
        "R4": r4(ctx, theta_params["A"], theta["A"], ctx["ev"]),
        "note": "The stitched S mixes per-fold configurations, so its drawdown is not that of any one shippable configuration.",
    }
    r_all = theta["A"]["ret"].to_numpy(dtype=float)
    dd_all = mc.block_bootstrap_drawdowns(r_all, mean_block=20, n_sims=1000, seed=0)
    fl = theta["A"].attrs["fills"]
    out["theta_final_in_sample"] = {
        "label": "IN-SAMPLE",
        "params": theta_params["A"],
        "max_drawdown": mc.max_drawdown(r_all),
        "mc_p5": mc.percentiles(dd_all, (5,))["p5"],
        "mc_p50": mc.percentiles(dd_all, (50,))["p50"],
        "worst_day": float(r_all.min()),
        **S.overshoot(theta["A"]["w_BTC"], theta["A"]["w_ETH"], ctx["limits"]),
        "legs_a_year": len(fl) / ((len(r_all) - 1) / 365),
        "leg_usd": {**mc.percentiles(fl["usd"]), "max": float(fl["usd"].max())} if len(fl) else {},
    }
    out["ranges"] = {
        f"{s:.2f}": {
            "grid": {
                "max_drawdown": grid[s]["drawdown"],
                "p5": grid[s]["p5"],
                "margin": grid[s]["p5"] + ctx["budget"],
                **drawdown_dates(grid[s]["series"]),
            },
            "S(s_k)": {
                "max_drawdown": sk[s]["drawdown"],
                "p5": sk[s]["p5"],
                "margin": sk[s]["p5"] + ctx["budget"],
                **drawdown_dates(sk[s]["bundle"]["S"]),
            },
            "most_crypto": S.overshoot(
                grid[s]["run"].loc[kept, "w_BTC"], grid[s]["run"].loc[kept, "w_ETH"], ctx["limits"]
            )["most_crypto"],
        }
        for s in T.ALLOWED_S
    }
    out["correlations"] = correlations(ctx, a_b)
    return out


def drawdown_dates(r: pd.Series) -> dict:
    value = np.cumprod(1.0 + r.to_numpy(dtype=float))
    high = np.maximum.accumulate(np.concatenate([[1.0], value]))[1:]
    dd = value / high - 1.0
    trough = int(np.argmin(dd))
    peak_rows = np.flatnonzero(value[: trough + 1] >= high[trough])
    return {
        "trough": r.index[trough].isoformat(),
        "peak": r.index[int(peak_rows[0])].isoformat() if len(peak_rows) else "start",
    }


def removal_row(ctx, b, it, mask) -> dict:
    e1_res = T.e1_test(b["R0"].to_numpy(), b["shifts"], b["W"], keep=mask)
    e2_res = e2(ctx, S.masked(b["S"], mask), S.masked(b["N0"], mask))
    sh = S.sharpe(S.masked(b["S"], mask))
    b1, b2 = S.sharpe(S.masked(ctx["B1"], mask)), S.sharpe(S.masked(ctx["B2"], mask))
    plateau = [S.sharpe(S.masked(r, mask)) for r in it["plateau_series"]]
    years = sorted(set(T.bar_years(b["kept"]).tolist()) - set(T.bar_years(b["kept"][mask]).tolist()))
    return {
        "removed": years,
        "e1_rank_p": e1_res["rank_p"],
        "E1": e1_res["holds"],
        "e2": S.e2_numbers(e2_res),
        "delta_y": it["e6"]["delta_y"].get(years[0]) if len(years) == 1 else None,
        "g7": S.point(sh > b1 and sh > b2, sh, b1, b2),
        "plateau": {"sharpe_S": sh, "steps": plateau, "holds": T.keeps_share(sh, plateau)},
    }


def stored_s_a(study: str, kept: pd.DatetimeIndex) -> pd.Series | None:
    """Column S_A of oos.parquet of ``study``'s last complete run under results/<study>/train/, or None."""
    base = S.REPO / "results" / study / "train"
    if not base.is_dir():
        return None
    runs = sorted((int(p.name[3:]), p) for p in base.glob("run*") if p.name[3:].isdigit())
    for _, path in reversed(runs):
        try:
            status = json.loads((path / "summary.json").read_text()).get("status")
        except (OSError, ValueError):
            continue
        if status == "complete" and (path / "oos.parquet").is_file():
            return pd.read_parquet(path / "oos.parquet", columns=["S_A"])["S_A"]
    return None


def correlations(ctx, b) -> dict:
    """INTERPRETATIONS["correlations"]: S's daily returns against B1, B2, N0 and the other Steady studies' S_A."""
    s = b["S"]
    out = {k: float(np.corrcoef(s, ctx[k] if k in ("B1", "B2") else b[k])[0, 1]) for k in ("B1", "B2", "N0")}
    for study in ("rebalance-steady", "trend-steady"):
        key = f"{study.replace('-', '_')}_S_A"
        out[key] = None
        other = stored_s_a(study, s.index) if ctx["data"] == "real" else None
        if other is not None:
            common = s.index.intersection(other.index)
            out[key] = float(np.corrcoef(s.loc[common], other.loc[common])[0, 1])
    return out


def out_files(args, ctx, run_dir, bundles, items, grid, sk, bn, evals, trials_all) -> None:
    kept = ctx["kept"]
    cols = {}
    for lab, b in bundles.items():
        for name in ("S", "S2", "R0", "N0", "N0_2", "X"):
            cols[f"{name}_{lab}"] = b[name]
        guarded = np.vstack([r for u, r in sorted(b["shifts"].items()) if u > T.LEAD_GUARD])
        for q in (5, 50, 95):
            cols[f"shifts_{lab}_p{q}"] = pd.Series(np.percentile(guarded, q, axis=0), index=kept)
    cols["B1"], cols["B2"] = ctx["B1"], ctx["B2"]
    for s, g in grid.items():
        cols[f"grid_{s:.2f}"] = g["series"]
        cols[f"grid_N0_{s:.2f}"] = g["n0"]
    for s, e in sk.items():
        bk = e["bundle"]
        cols[f"S_sk_{s:.2f}"], cols[f"R0_sk_{s:.2f}"], cols[f"N0_sk_{s:.2f}"] = bk["S"], bk["R0"], bk["N0"]
        m = np.vstack(list(bk["shifts"].values()))
        for q in (5, 50, 95):
            cols[f"shifts_sk_{s:.2f}_p{q}"] = pd.Series(np.percentile(m, q, axis=0), index=kept)
    oos = pd.DataFrame({k: v.reindex(kept) for k, v in cols.items()})
    oos["N0_span"] = ctx["N0_span"]
    oos["S_binance_A"] = bn["S"].reindex(kept)
    oos["N0_binance_A"] = bn["N0"].reindex(kept)
    oos.to_parquet(run_dir / "oos.parquet")
    evals.to_parquet(run_dir / "evaluations.parquet")
    trials_all.to_parquet(run_dir / "trials.parquet")
    tracked = S.tracked_dir(Path(args.out_dir), args.synthetic is not None)
    tracked.mkdir(parents=True, exist_ok=True)
    trials_all.to_csv(tracked / "trials.csv", index=False)
    every = [
        pd.read_parquet(p)
        for j in range(ctx["k"] + 1)
        if (p := ctx["train"] / f"run{j}" / "evaluations.parquet").is_file()
    ]
    pd.concat(every, ignore_index=True).to_csv(tracked / "evaluations.csv", index=False)


def pending(reported: Mapping) -> str | None:
    """A train headline is not final while the look is due: E9 decides it at the single validate look (section 12)."""
    return "E9 at the single validate look" if reported["look_earned"] is True else None


def reported_block(train: Path, k: int, own: Mapping, start: Mapping) -> dict:
    """Stop rule 18 (INTERPRETATIONS["reported"]): run k's reported verdict, headline, stop outcome and look_earned
    from its own record and the earlier runs its start record says it is reported beside; every complete run's E1
    rank p and E2 p. An earlier run that crashed or stopped has no results and lists nothing."""
    beside = start["beside"]
    runs = []
    for j in range(k):
        prev = S.run_summary(train, j)
        if prev.get("status") == "complete":
            runs.append({"run": j, **{key: prev["results"]["own"][key] for key in ("e1_rank_p", "e2_p")}})
    runs.append({"run": k, "e1_rank_p": own["e1_rank_p"], "e2_p": own["e2_p"]})
    return {
        **S.combine_reported(beside, own),
        "superseded": None if k == 0 else start["trigger"] != S.OTHER,
        "trigger": start["trigger"],
        "beside": beside,
        "runs": runs,
    }


def earlier_runs(train: Path, k: int) -> dict:
    earlier = {}
    for j in range(k):
        prev = json.loads((train / f"run{j}" / "summary.json").read_text())
        res = prev.get("results", {})
        earlier[j] = {
            "status": prev.get("status"),
            "verdict": res.get("verdict"),
            "headline": res.get("headline"),
            "e1_rank_p": res.get("seeds", {}).get("A", {}).get("e1", {}).get("rank_p"),
            "e2_p": res.get("seeds", {}).get("A", {}).get("e2", {}).get("p"),
        }
    return earlier


# ------------------------------------------------------------------------------------------------ the run


def start_guards(args) -> dict:
    synthetic = args.synthetic is not None
    if not synthetic and (args.fast or args.allow_dirty):
        raise S.Refusal("--fast and --allow-dirty are for synthetic dry runs only")
    if args.amendment == 0:
        raise S.Refusal("--amendment 0: run 0 is run without --amendment")
    k = 0 if args.amendment is None else args.amendment
    if k == 0 and args.trigger is not None:
        raise S.Refusal("--trigger is for amendment runs only (stop rule 18)")
    out = Path(args.out_dir)
    config_dir = Path(args.config_dir) if args.config_dir else None
    S.check_paths(out, config_dir, Path(args.catalog_dir), synthetic)
    train = out / "train"
    check_layout(train, k)
    data = "synthetic" if synthetic else "real"
    beside = []
    if k:
        check_earlier_runs(train, k, data, bool(args.fast))
        if args.trigger not in S.TRIGGERS:
            raise S.Refusal(
                f"--amendment {k} needs --trigger, one of {S.TRIGGERS} (stop rule 18); got {args.trigger!r}"
            )
        beside = S.beside_runs(train, k, args.trigger)
    check_runlog(S.runlog_path(out, synthetic), k, data)
    plan_text = S.PLAN.read_text()
    if k and not synthetic and not S.amendment_row_present(plan_text, k):
        raise S.Refusal(
            f"--amendment {k}: PLAN.md section 15 has no '- **Amendment run {k}' row (stop rule 7)"
        )
    git = S.git_state()
    if git["dirty"] and not (synthetic and args.allow_dirty):
        raise S.Refusal(
            f"the git tree is dirty (git status --porcelain --untracked-files=all): commit first. Changes: {git['changes'][:10]}"
        )
    prior = None if synthetic else S.prior_amendments(plan_text, S.PLAN_SETTINGS.n_trials)
    hashes = S.file_hashes(config_dir)
    snapshot = S.read_snapshot(Path(args.catalog_dir), synthetic)
    try:
        limits = sd.steady_limits(config_dir)
    except ValueError as exc:
        raise S.Refusal(f"risk_limits('steady') does not read (section 4): {exc}") from exc
    branch = S.check_branch(limits, plan_text)
    try:
        feasible = V.check_feasibility(limits)
    except ValueError as exc:
        raise S.Refusal(
            f"stop rule 12: a target set the run can order breaks the limits as read: {exc}"
        ) from exc
    settings = S.FAST if args.fast else S.PLAN_SETTINGS
    costs1 = S.costs_for(config_dir)
    try:
        timing = S.measure_timing(limits, costs1, settings, settings.n_trials)
    except Exception as exc:  # the engine fails on the timing's synthetic panel: nothing can run
        raise S.Refusal(f"stop rule 17: the re-timing failed: {type(exc).__name__}: {exc}") from exc
    proj = S.projection(timing, S.run_counts(), T.RUN_BUDGET_MINUTES)
    if not synthetic and not proj["allows"]:
        raise S.Refusal(
            f"stop rule 17: the projection is {proj['cpu_minutes']:.1f} CPU-minutes, above {T.RUN_BUDGET_MINUTES}: "
            "ask the owner (the budget is not raised to let a run start)"
        )
    return {
        "k": k,
        "out": out,
        "train": train,
        "config_dir": config_dir,
        "data": data,
        "synthetic": synthetic,
        "git": git,
        "hashes": hashes,
        "snapshot": snapshot,
        "limits": limits,
        "branch": branch,
        "feasible": feasible,
        "settings": settings,
        "costs1": costs1,
        "timing": timing,
        "projection": proj,
        "beside": beside,
        "prior_amendments": prior,
    }


def run(args) -> int:
    g = start_guards(args)
    k, out, train, settings = g["k"], g["out"], g["train"], g["settings"]
    start = {
        "utc": S.utc_now(),
        "script": "run_train.py",
        "data": g["data"],
        "synthetic_seed": args.synthetic,
        "git": g["git"],
        "config_hash": S.config_hash(g["hashes"]),
        "file_hashes": g["hashes"],
        "snapshot": g["snapshot"],
        "branch": g["branch"],
        "risk_limits": g["limits"],
        "g6_budget": g6_budget(train, k, g["limits"]),
        "feasible_shares": g["feasible"],
        "settings": asdict(settings),
        "fast": bool(args.fast),
        "config_dir": str(g["config_dir"]) if g["config_dir"] else None,
        "trigger": args.trigger,
        "beside": g["beside"],
        "prior_amendments": g["prior_amendments"],
        "timing": g["timing"],
        "projection": g["projection"],
        "run_counts": S.run_counts(),
        "label": S.LABEL,
    }
    S.append_runlog(
        S.runlog_path(out, g["synthetic"]),
        {
            "utc": start["utc"],
            "script": "run_train.py",
            "run": k,
            "commit": g["git"]["commit"],
            "dirty": g["git"]["dirty"],
            "config_hash": start["config_hash"],
            "snapshot_id": g["snapshot"]["snapshot_id"],
            "data": g["data"],
            "trigger": args.trigger,
            "out_dir": str(out),
        },
    )
    run_dir = train / f"run{k}"
    run_dir.mkdir(parents=True)
    summary = {"study": S.STUDY, "run": k, "status": "started", "start": S.jsonable(start)}
    S.write_json(run_dir / "summary.json", summary)
    print(
        f"run {k} ({g['data']}) started; config hash {start['config_hash'][:16]}; projection "
        f"{g['projection']['cpu_minutes']:.1f} CPU-minutes; budget {g['limits']['max_drawdown_budget']}",
        flush=True,
    )
    costs1 = g["costs1"]
    costs2 = costs1.stressed()
    ctx = {
        "k": k,
        "train": train,
        "config_dir": g["config_dir"],
        "data": g["data"],
        "limits": g["limits"],
        "budget": start["g6_budget"]["max_drawdown_budget"],
        "costs1": costs1,
        "costs2": costs2,
        "fn1": partial(V.vol_backtest, limits=g["limits"], costs=costs1),
        "fn2": partial(V.vol_backtest, limits=g["limits"], costs=costs2),
        "settings": settings,
        "tally": S.Tally(),
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
    except ValueError as exc:
        if "stop rule 12" not in str(exc):
            summary["status"] = f"crashed: {type(exc).__name__}: {exc}"
            S.write_json(run_dir / "summary.json", summary)
            raise
        summary["status"] = f"stopped: stop rule 12: {exc}"
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
    print(
        f"run {k} complete in {time.time() - t:.1f}s. Verdict: {results['verdict']['label']}; headline: "
        f"{results['headline']['headline']}; reported (stop rule 18): {results['reported']['verdict']}, "
        f"{results['reported']['headline']}"
        + (f" (pending: {results['pending']})" if results["pending"] else "")
        + f"; failed trials {len(results['failed_trials'])}",
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
