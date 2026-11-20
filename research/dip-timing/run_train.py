"""Train-window run of the dip-timing study: event-level CPCV of V01-V40 (PLAN.md sections 5-7).

SCOUTING ONLY (reference backtester, not NautilusTrader; AGENTS.md hard rule 3). Reads only bars and positioning
closing up to 2023-01-01 00:00 UTC (the train window); never the validate or test windows.

    uv run python research/dip-timing/run_train.py                 # the one real run (refuses to overwrite)
    uv run python research/dip-timing/run_train.py --synthetic --out <scratch>   # pipeline dry run, no real data

Every variant is appended to <out>/trials.jsonl as soon as it finishes or fails, then written to
<out>/trials.parquet and research/dip-timing/trials.csv.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd
import study as S

from lab.models import dips
from lab.models.train import class_metrics
from lab.runner.reference import Costs
from lab.validation import stats


class TrialLog:
    def __init__(self, out: Path, meta: dict):
        self.rows: list[dict] = []
        self.path = out / "trials.jsonl"
        self.meta = meta

    def add(self, vid: str, definition: dict, recipe: S.Recipe, status: str, metrics: dict | None) -> None:
        d = recipe.describe()
        row = {
            "id": vid,
            "definition": json.dumps(definition, sort_keys=True),
            "rule": d["rule"],
            "filter": d["filter"] or "",
            "model": d["model"],
            "features": json.dumps({"q": S.q_cols(recipe) if recipe.filter else [],
                                    "b": S.b_cols(recipe) if recipe.timing == "T5" else []}),
            "subset": d["subset"],
            "theta_shift": d["theta_shift"],
            "window": "train 2017-01-01..2022-12-31, event CPCV 6 groups / 2 test (15 splits, 5 paths)",
            "snapshot": self.meta["snapshot"],
            "commit": self.meta["commit"],
            "config_hash": self.meta["config_hash"],
            "seed": S.SEED,
            "status": status,
            "label": S.LABEL,
            "metrics": json.dumps(S.jsonable(metrics or {}), sort_keys=True),
        }
        for k in ("n_events", "mean_r", "mean_delta", "p_boot", "paths_delta_positive", "skip_share"):
            row[k] = (metrics or {}).get(k)
        if metrics and "strategy_sharpe_paths" in metrics:
            row["sharpe_paths"] = json.dumps(S.jsonable(metrics["strategy_sharpe_paths"]))
        self.rows.append(row)
        with self.path.open("a") as fh:
            fh.write(json.dumps(S.jsonable(row)) + "\n")

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def definition_of(es: S.EventSet, source: str) -> dict:
    s = es.spec
    return {"X": s.drop, "N": s.lookback, "H": s.hold, "K": s.entry_window, "stop": s.stop,
            "costs_x": round(es.costs.pool_fee_bps / Costs.from_yaml().pool_fee_bps, 6), "bars": source,
            "eventset": es.name}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(S.REPO / "results/dip-timing/train"))
    ap.add_argument("--trials-csv", default=str(S.HERE / "trials.csv"))
    ap.add_argument("--synthetic", action="store_true", help="dry run on synthetic bars (no real data)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if (out / "trials.jsonl").exists():
        print(f"{out}/trials.jsonl exists: the train run is never rerun in place (PLAN.md section 7). "
              "A rerun after a fix is a logged amendment with new IDs.", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    costs = Costs.from_yaml()
    if args.synthetic:
        market = S.synthetic_market_for_dry_run(7, S.TRAIN_LAST_CLOSE)
        binance = S.synthetic_market_for_dry_run(8, S.TRAIN_LAST_CLOSE)
    else:
        market = S.load_market("kraken", S.TRAIN_LAST_CLOSE)
        binance = S.load_market("binance", S.TRAIN_LAST_CLOSE)
    for m in (market, binance):
        for coin, b in m.bars.items():
            dips.check_before_holdout(b.index)
            assert b.index.max() <= S.TRAIN_LAST_CLOSE, "the train run reads train bars only"
            assert m.pos[coin].index.max() <= S.TRAIN_LAST_CLOSE
    git = S.git_state()
    meta = {"snapshot": market.snapshot, "commit": f"{git['commit']}{'+dirty' if git['dirty'] else ''}",
            "config_hash": S.config_hash()}
    log = TrialLog(out, meta)
    d0 = S.build_eventset("D0", market, S.D0, costs, S.TRAIN)
    counts = d0.events.groupby("coin").size().to_dict()
    coverage = {
        "funding": d0.events.loc[d0.events["funding_covered"]].groupby("coin").size().to_dict(),
        "oi": d0.events.loc[d0.events["oi_covered"]].groupby("coin").size().to_dict(),
    }
    print("D0 train events", counts, "coverage", coverage, flush=True)
    if not args.synthetic:
        assert counts == {"BTC": 37, "ETH": 43}, counts  # PLAN.md section 2 counting run

    results: dict[str, S.VariantResult] = {}
    summaries: dict[str, dict] = {}

    def run(vid: str, es: S.EventSet, recipe: S.Recipe, source: str = "kraken") -> S.VariantResult:
        definition = definition_of(es, source)
        try:
            vr = S.evaluate(vid, es, recipe)
            S.run_strategy(vr)
        except Exception as exc:
            log.add(vid, definition, recipe, f"failed: {exc!r}", None)
            raise
        results[vid] = vr
        summaries[vid] = S.summarize(vr)
        log.add(vid, definition, recipe, "ok", summaries[vid])
        s = summaries[vid]
        print(f"{vid} {es.name:12s} n={s['n_events']:3d} mean_r={s['mean_r']:+.4f} delta={s['mean_delta']:+.4f} "
              f"p={s['p_boot']:.3f} sharpe={np.median(s['strategy_sharpe_paths']):+.3f}", flush=True)
        return vr

    # ---------------------------------------------------------------- primary variants (V01-V10)
    rec = {
        "V01": S.Recipe("T1"), "V02": S.Recipe("T2"), "V03": S.Recipe("T3"), "V04": S.Recipe("T4"),
        "V05": S.Recipe("T5", b_model="logistic"), "V06": S.Recipe("T5", b_model="lightgbm"),
        "V07": S.Recipe("T1", filter="vol"), "V08": S.Recipe("T1", filter="Q"),
    }
    for vid, r in rec.items():
        run(vid, d0, r)
    better_t5 = "V05" if summaries["V05"]["mean_r"] >= summaries["V06"]["mean_r"] else "V06"
    best_rule = max(("V02", "V03", "V04"), key=lambda v: summaries[v]["mean_r"])
    rec["V09"] = replace(rec[better_t5], filter="Q")
    rec["V10"] = S.Recipe(rec[best_rule].timing, filter="Q")
    run("V09", d0, rec["V09"])
    run("V10", d0, rec["V10"])
    # ---------------------------------------------------------------- positioning pairs (V11-V16)
    rec["V11"] = S.Recipe("T1", filter="Q", subset="funding")
    rec["V12"] = S.Recipe("T1", filter="Q", q_extra=("funding_7d",), subset="funding")
    rec["V13"] = S.Recipe("T5", b_model="logistic", subset="funding")
    rec["V14"] = S.Recipe("T5", b_model="logistic", b_extra=("funding_7d",), subset="funding")
    rec["V15"] = S.Recipe("T1", filter="Q", subset="oi")
    rec["V16"] = S.Recipe("T1", filter="Q", q_extra=("funding_7d", "oi_chg_dip"), subset="oi")
    for vid in ("V11", "V12", "V13", "V14", "V15", "V16"):
        run(vid, d0, rec[vid])

    # ---------------------------------------------------------------- nulls and criteria 1-3
    table = S.single_entry_table(d0)
    assert np.array_equal(table[:, 0], d0.events["r_T1"].to_numpy()), "offset 0 is T1"
    nulls = {"timing": S.null_means(table, "timing")}
    primary = [f"V{i:02d}" for i in range(2, 11)]
    model_vids = {"V05", "V06", "V07", "V08", "V09", "V10"}
    for vid in ("V07", "V08", "V09", "V10"):
        k = int(round(summaries[vid]["skip_count_mean"]))
        nulls[f"skip_{vid}"] = S.null_means(table, "skip", k)
        nulls[f"both_{vid}"] = S.null_means(table, "both", k)
    p_raw = np.array([summaries[v]["p_boot"] for v in primary])
    p_holm = dips.holm(p_raw)
    criteria: dict[str, dict] = {}
    for v, pr, ph in zip(primary, p_raw, p_holm, strict=True):
        s = summaries[v]
        c = {"p_raw": float(pr), "p_holm": float(ph), "c1": bool(ph < 0.05)}
        c["c2"] = bool(s["paths_delta_positive"] >= 4) if v in model_vids else None
        tq = float(np.quantile(nulls["timing"], 0.95))
        if v in ("V02", "V03", "V04", "V05", "V06"):
            c["null95"] = {"timing": tq}
            c["c3"] = bool(s["mean_r"] > tq)
        elif v in ("V07", "V08"):
            sq = float(np.quantile(nulls[f"skip_{v}"], 0.95))
            c["null95"] = {"skip": sq}
            c["c3"] = bool(s["mean_r"] > sq)
        else:
            sq = float(np.quantile(nulls[f"skip_{v}"], 0.95))
            bq = float(np.quantile(nulls[f"both_{v}"], 0.95))
            c["null95"] = {"timing": tq, "skip": sq, "both_reported": bq}
            c["c3"] = bool(s["mean_r"] > tq and s["mean_r"] > sq)
        c["passes_1_3"] = bool(c["c1"] and (c["c2"] in (None, True)) and c["c3"])
        criteria[v] = c
    passing = [v for v in primary if criteria[v]["passes_1_3"]]
    pool = passing or [f"V{i:02d}" for i in range(1, 11)]
    best = max(pool, key=lambda v: summaries[v]["mean_r"])
    print("criteria 1-3 passing:", passing, "best:", best, flush=True)

    # ---------------------------------------------------------------- sensitivity (V17-V40)
    others = [c for c in S.CELLS if c != (S.D0.drop, S.D0.lookback)]
    cell_sets = {c: S.build_eventset(f"X{c[0]:.2f}_N{c[1]}", market, replace(S.D0, drop=c[0], lookback=c[1]),
                                     costs, S.TRAIN) for c in others}
    for i, c in enumerate(others):
        rec[f"V{17 + i}"] = S.Recipe("T1")
        run(f"V{17 + i}", cell_sets[c], rec[f"V{17 + i}"])
    for i, c in enumerate(others):
        rec[f"V{25 + i}"] = rec[best]
        run(f"V{25 + i}", cell_sets[c], rec[best])
    theta_base = best if rec[best].fitted else max(sorted(model_vids), key=lambda v: summaries[v]["mean_r"])
    rec["V33"] = replace(rec[theta_base], theta_shift=+S.THETA_SHIFT)
    rec["V34"] = replace(rec[theta_base], theta_shift=-S.THETA_SHIFT)
    run("V33", d0, rec["V33"])
    run("V34", d0, rec["V34"])
    es_2x = S.build_eventset("D0_costs2x", market, S.D0, costs.stressed(2.0), S.TRAIN)
    rec["V35"], rec["V36"] = rec[best], S.Recipe("T1")
    run("V35", es_2x, rec["V35"])
    run("V36", es_2x, rec["V36"])
    es_bn = S.build_eventset("D0_binance", binance, S.D0, costs, S.TRAIN)
    rec["V37"], rec["V38"] = rec[best], S.Recipe("T1")
    run("V37", es_bn, rec["V37"], "binance")
    run("V38", es_bn, rec["V38"], "binance")
    es_h20 = S.build_eventset("D0_H20", market, replace(S.D0, hold=20), costs, S.TRAIN)
    rec["V39"] = rec[best]
    run("V39", es_h20, rec["V39"])
    es_s10 = S.build_eventset("D0_stop10", market, replace(S.D0, stop=0.10), costs, S.TRAIN)
    rec["V40"] = rec[best]
    run("V40", es_s10, rec["V40"])
    references = {}
    for name, es in (("T1_H20", es_h20), ("T1_stop10", es_s10)):
        ref = S.evaluate(name, es, S.Recipe("T1"))
        S.run_strategy(ref)
        references[name] = S.summarize(ref)

    # ---------------------------------------------------------------- PBO, DSR, criteria 4-7
    vids = [f"V{i:02d}" for i in range(1, 41)]
    assert len(log.rows) == 40 and all(r["status"] == "ok" for r in log.rows)
    index = results["V01"].series[0].index
    pbo_paths = []
    for j in range(S.N_PATHS):
        m = np.column_stack([results[v].series[j].reindex(index).fillna(0.0).to_numpy() for v in vids])
        pbo_paths.append(stats.pbo(m, n_blocks=S.PBO_BLOCKS)["pbo"])
    med = {v: results[v].series[S.median_path(results[v])].reindex(index).fillna(0.0).to_numpy() for v in vids}
    med_matrix = np.column_stack([med[v] for v in vids])
    trial_sharpes = stats.column_sharpes(med_matrix)
    n_raw = len(log.rows)
    n_eff = stats.effective_trials(med_matrix)
    dsr_raw = stats.deflated_sharpe_ratio(med[best], trial_sharpes, n_trials=n_raw)
    dsr_eff = stats.deflated_sharpe_ratio(med[best], trial_sharpes, n_trials=max(n_eff, 1.0))
    t1_sharpe = summaries["V01"]["strategy_sharpe_paths"][0]
    for v in primary:
        sp = summaries[v]["strategy_sharpe_paths"]
        criteria[v]["c6_paths_above_t1"] = int(sum(x > t1_sharpe for x in sp))
    cell_delta = {"D0": summaries[best]["mean_delta"]}
    for i, c in enumerate(others):
        r_best = results[f"V{25 + i}"].r.mean(axis=0)
        r_t1 = results[f"V{17 + i}"].r.mean(axis=0)
        cell_delta[f"X{c[0]:.2f}_N{c[1]}"] = float((r_best - r_t1).mean())
    c4_delta = float((results["V35"].r.mean(axis=0) - results["V36"].r.mean(axis=0)).mean())
    best_c = {
        "best": best,
        "c4_delta_costs_2x": c4_delta,
        "c4": c4_delta > 0,
        "c5_cell_delta": cell_delta,
        "c5_cells_positive": int(sum(d > 0 for d in cell_delta.values())),
        "c5": sum(d > 0 for d in cell_delta.values()) >= 6,
        "c6_paths_above_t1": int(sum(x > t1_sharpe for x in summaries[best]["strategy_sharpe_paths"])),
        "pbo_paths": pbo_paths,
        "pbo": float(np.mean(pbo_paths)),
        "dsr_raw": dsr_raw,
        "dsr_effective": dsr_eff,
        "n_trials_raw": n_raw,
        "n_trials_effective": n_eff,
        "binance_delta": float((results["V37"].r.mean(axis=0) - results["V38"].r.mean(axis=0)).mean()),
        "h20_delta_vs_t1": float(summaries["V39"]["mean_r"] - references["T1_H20"]["mean_r"]),
        "stop10_delta_vs_t1": float(summaries["V40"]["mean_r"] - references["T1_stop10"]["mean_r"]),
    }
    best_c["c6"] = bool(best_c["c6_paths_above_t1"] >= 4 and best_c["pbo"] <= 0.25)

    # ---------------------------------------------------------------- positioning value
    pairs = [("V12", "V11"), ("V14", "V13"), ("V16", "V15")]
    pos_tests = []
    for with_, without in pairs:
        a, b = results[with_], results[without]
        assert np.array_equal(a.events, b.events)
        delta = a.r.mean(axis=0) - b.r.mean(axis=0)
        boot = dips.month_bootstrap(delta, d0.events.loc[a.events, "month"].to_numpy(), S.N_BOOT, S.SEED)
        pos_tests.append({"with": with_, "without": without, "n_events": len(delta), **boot})
    for t, ph in zip(pos_tests, dips.holm([t["p"] for t in pos_tests]), strict=True):
        t["p_holm"] = float(ph)
        t["adds_value"] = bool(ph < 0.05 and t["mean"] > 0)

    # ---------------------------------------------------------------- forecast quality (AUC), baselines
    fq = {v: {"q_auc": results[v].auc["q"], "b_auc": results[v].auc["b"]} for v in
          ("V05", "V06", "V07", "V08", "V11", "V12", "V13", "V14", "V15", "V16")}
    score_auc: dict[str, list] = {"b_up_day": [], "neg_b_range_ratio": [], "neg_b_depth": [], "b_days": [],
                                  "b_bounce": []}
    sub_ts0, sub_end = d0.events["ts0"], d0.events["ts_end"]
    for _, test_pos, _ in dips.event_cpcv(sub_ts0, sub_end, S.N_GROUPS, S.N_TEST_GROUPS, pd.Timedelta(days=31)):
        te = d0.days.loc[d0.days["event"].isin(test_pos)]
        y = te["y_B"].to_numpy()
        score_auc["b_up_day"].append(class_metrics(y, te["b_up_day"])["auc"])
        score_auc["neg_b_range_ratio"].append(class_metrics(y, -te["b_range_ratio"])["auc"])
        score_auc["neg_b_depth"].append(class_metrics(y, -te["b_depth"])["auc"])
        score_auc["b_days"].append(class_metrics(y, te["b_days"])["auc"])
        score_auc["b_bounce"].append(class_metrics(y, te["b_bounce"])["auc"])
    by_offset = {
        "mean_r": table.mean(axis=0).tolist(),
        "median_r": np.median(table, axis=0).tolist(),
        "share_positive": (table > 0).mean(axis=0).tolist(),
        "distance_mean": [float(np.mean([S.outcome(d0, e, ((o, 1.0),))["distance"]
                                         for e in range(len(d0.events))])) for o in range(d0.spec.entry_window)],
    }
    hindsight = {
        "best_offset_mean_r": float(table.max(axis=1).mean()),
        "worst_offset_mean_r": float(table.min(axis=1).mean()),
        "skip_every_loser_mean_r": float(np.maximum(table[:, 0], 0.0).mean()),
    }
    n_t1 = d0.events.groupby("coin").size().to_dict()
    bench = S.benchmarks(d0, n_t1)
    t1_strategy = summaries["V01"]
    bench_summary = {
        "buy_and_hold": {k: v for k, v in bench["buy_and_hold"].items() if k != "series"},
        "mix_50_50_every_30": {k: v for k, v in bench["mix_50_50_every_30"].items() if k != "series"},
        "random_entry_sharpe_pct": {q: float(np.percentile(bench["random_entry"]["sharpe"], q)) for q in (5, 50, 95)},
        "t1_sharpe_rank_vs_random_entry": float(np.mean(np.array(bench["random_entry"]["sharpe"])
                                                        < t1_strategy["strategy_sharpe_paths"][0])),
        "random_entry_total_return_pct": {q: float(np.percentile(bench["random_entry"]["total_return"], q))
                                          for q in (5, 50, 95)},
    }
    per_coin = {}
    for v in ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10"):
        vr = results[v]
        coins = d0.events.loc[vr.events, "coin"].to_numpy()
        per_coin[v] = {c: {"n": int((coins == c).sum()),
                           "mean_r": float(vr.r.mean(axis=0)[coins == c].mean()),
                           "mean_delta": float(vr.delta.mean(axis=0)[coins == c].mean())} for c in S.COINS}

    # ---------------------------------------------------------------- write
    trials = log.frame()
    trials.to_parquet(out / "trials.parquet", index=False)
    if not args.synthetic:
        trials.to_csv(args.trials_csv, index=False)
    series = pd.DataFrame({f"{v}_path{j}": results[v].series[j].reindex(index).fillna(0.0)
                           for v in vids for j in range(S.N_PATHS)})
    series.attrs = {}
    series.to_parquet(out / "series.parquet")
    ev_table = d0.events.drop(columns=["local"]).copy()
    for v in vids[:16]:
        vr = results[v]
        if vr.es is d0:
            col = np.full(len(d0.events), np.nan)
            col[vr.events] = vr.r.mean(axis=0)
            ev_table[f"r_{v}"] = col
    ev_table.to_parquet(out / "events_d0.parquet", index=False)
    summary = {
        "label": S.LABEL,
        "window": "train",
        "synthetic": bool(args.synthetic),
        "snapshot": market.snapshot,
        "git": git,
        "config_hash": meta["config_hash"],
        "code_hashes": S.code_hashes(),
        "interpretations": S.INTERPRETATIONS,
        "runtime_s": time.time() - t_start,
        "last_close_read": S.TRAIN_LAST_CLOSE.isoformat(),
        "counts": counts,
        "coverage": coverage,
        "eventsets": {es.name: {"n": len(es.events), "by_coin": es.events.groupby("coin").size().to_dict(),
                                "y_Q_share": float(es.events["y_Q"].mean()),
                                "y_B_share": float(es.days["y_B"].mean())}
                      for es in [d0, es_2x, es_bn, es_h20, es_s10, *cell_sets.values()]},
        "selections": {"better_t5": better_t5, "best_t2_t4": best_rule, "best": best, "theta_base": theta_base},
        "recipes": {vid: asdict(r) for vid, r in rec.items()},
        "summaries": summaries,
        "references": references,
        "criteria_primary": criteria,
        "criteria_best": best_c,
        "nulls": {k: {"mean": float(v.mean()), "p95": float(np.quantile(v, 0.95)), "p5": float(np.quantile(v, 0.05))}
                  for k, v in nulls.items()},
        "positioning_value": pos_tests,
        "forecast_quality": fq,
        "score_auc_b": score_auc,
        "by_offset": by_offset,
        "hindsight": hindsight,
        "benchmarks": bench_summary,
        "per_coin": per_coin,
        "n_trials_logged": n_raw,
    }
    (out / "summary.json").write_text(json.dumps(S.jsonable(summary), indent=1, sort_keys=True))
    print(f"done in {time.time() - t_start:.1f}s; best {best}; PBO {best_c['pbo']:.3f}; "
          f"DSR eff {dsr_eff['dsr']:.3f} (n_eff {n_eff:.2f})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
