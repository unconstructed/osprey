"""The single validate look of the dip-timing study (PLAN.md section 6; look #1 of section 9).

SCOUTING ONLY (reference backtester, not NautilusTrader; AGENTS.md hard rule 3). Reads bars and positioning
closing up to 2024-07-01 00:00 UTC (train + validate) and never anything later: the loaders refuse it and every
frame is checked again here.

Runs once. It refuses to start if <out>/look.json exists (no second look) or if the code and config no longer match
results/dip-timing/FROZEN.json (written after the train run, before this look). Models are refit once on all train
events and applied to the validate events; V01-V16, the baselines and the nulls are reported; nothing is tuned.

    uv run python research/dip-timing/run_validate.py
    uv run python research/dip-timing/run_validate.py --synthetic --train <scratch>/train --out <scratch>/validate
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import study as S

from lab.models import dips
from lab.runner.reference import Costs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train", default=str(S.REPO / "results/dip-timing/train"))
    ap.add_argument("--out", default=str(S.REPO / "results/dip-timing/validate"))
    ap.add_argument("--frozen", default=str(S.REPO / "results/dip-timing/FROZEN.json"))
    ap.add_argument("--csv", default=str(S.HERE / "validate.csv"))
    ap.add_argument("--synthetic", action="store_true", help="dry run on synthetic bars (no real data)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if (out / "look.json").exists() or (out / "STARTED").exists():
        print(f"{out}: the validate window was already looked at; there is no second look (PLAN.md section 8).",
              file=sys.stderr)
        return 2
    frozen = json.loads(Path(args.frozen).read_text())
    if frozen["config_hash"] != S.config_hash() or frozen["code_hashes"] != S.code_hashes():
        print("code or config changed since FROZEN.json: the look must use the frozen code", file=sys.stderr)
        return 3
    train = json.loads((Path(args.train) / "summary.json").read_text())
    assert train["synthetic"] == args.synthetic
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    (out / "STARTED").write_text(started + "\n")  # marks the look as taken even if it crashes
    t0 = time.time()
    costs = Costs.from_yaml()
    if args.synthetic:
        market = S.synthetic_market_for_dry_run(7, S.VALIDATE_LAST_CLOSE)
    else:
        market = S.load_market("kraken", S.VALIDATE_LAST_CLOSE)
    for coin, b in market.bars.items():
        dips.check_before_holdout(b.index)
        dips.check_before_holdout(market.pos[coin].index)
        assert b.index.max() <= S.VALIDATE_LAST_CLOSE
    es_tr = S.build_eventset("D0_train", market, S.D0, costs, S.TRAIN)
    es_va = S.build_eventset("D0_validate", market, S.D0, costs, S.VALIDATE)
    train_events = pd.read_parquet(Path(args.train) / "events_d0.parquet")
    # the train events and their T1 outcomes are reproduced exactly from the longer series
    assert es_tr.events["ts0"].tolist() == train_events["ts0"].tolist()
    np.testing.assert_array_equal(es_tr.events["r_T1"].to_numpy(), train_events["r_T1"].to_numpy())
    counts = es_va.events.groupby("coin").size().to_dict()
    print("validate events", counts, flush=True)
    if not args.synthetic:
        assert counts == {"BTC": 4, "ETH": 4}, counts  # PLAN.md section 2

    recipes = {vid: S.Recipe(**{k: tuple(v) if isinstance(v, list) else v for k, v in r.items()})
               for vid, r in train["recipes"].items() if int(vid[1:]) <= 16}
    results, summaries = {}, {}
    for vid, recipe in recipes.items():
        vr = S.evaluate_holdout(vid, es_tr, es_va, recipe)
        S.run_strategy(vr)
        results[vid] = vr
        summaries[vid] = S.summarize(vr)
        s = summaries[vid]
        print(f"{vid} n={s['n_events']} mean_r={s['mean_r']:+.4f} delta={s['mean_delta']:+.4f} "
              f"sharpe={s['strategy_sharpe_paths'][0]:+.3f}", flush=True)
    table = S.single_entry_table(es_va)
    nulls = {"timing": S.null_means(table, "timing")}
    for vid in ("V07", "V08", "V09", "V10"):
        k = int(round(summaries[vid]["skip_count_mean"]))
        nulls[f"skip_{vid}"] = S.null_means(table, "skip", k)
    bench = S.benchmarks(es_va, es_va.events.groupby("coin").size().to_dict())
    best = train["selections"]["best"]
    per_event = es_va.events[["coin", "ts0", "ts_end", "p_ref", "r_T1", "y_Q", "funding_7d", "oi_chg_dip"]].copy()
    for vid, vr in results.items():
        col = np.full(len(es_va.events), np.nan)
        col[vr.events] = vr.r[0]
        per_event[f"r_{vid}"] = col
    look = {
        "label": S.LABEL,
        "window": "validate (2023-01-01 .. 2024-06-30), single look",
        "synthetic": bool(args.synthetic),
        "started_utc": started,
        "runtime_s": time.time() - t0,
        "last_close_read": S.VALIDATE_LAST_CLOSE.isoformat(),
        "config_hash": S.config_hash(),
        "snapshot": market.snapshot,
        "counts": counts,
        "best": best,
        "criterion_7": {"best_mean_delta": summaries[best]["mean_delta"], "pass": summaries[best]["mean_delta"] >= 0},
        "summaries": summaries,
        "fits": {vid: S.jsonable(vr.splits_meta) for vid, vr in results.items()},
        "nulls": {k: {"mean": float(v.mean()), "p5": float(np.quantile(v, 0.05)), "p95": float(np.quantile(v, 0.95))}
                  for k, v in nulls.items()},
        "by_offset_mean_r": table.mean(axis=0).tolist(),
        "benchmarks": {
            "buy_and_hold": {k: v for k, v in bench["buy_and_hold"].items() if k != "series"},
            "mix_50_50_every_30": {k: v for k, v in bench["mix_50_50_every_30"].items() if k != "series"},
            "random_entry_sharpe_pct": {q: float(np.percentile(bench["random_entry"]["sharpe"], q)) for q in (5, 50, 95)},
        },
        "events": S.jsonable(per_event.to_dict(orient="records")),
    }
    (out / "look.json").write_text(json.dumps(S.jsonable(look), indent=1, sort_keys=True))
    per_event.to_parquet(out / "events.parquet", index=False)
    rows = [{"id": vid, "window": "validate", "label": S.LABEL, "config_hash": look["config_hash"],
             "snapshot": market.snapshot, **{k: summaries[vid][k] for k in
                                             ("n_events", "mean_r", "mean_r_t1", "mean_delta", "skip_share",
                                              "forced_share", "distance_mean", "mae_mean")},
             "sharpe": summaries[vid]["strategy_sharpe_paths"][0],
             "total_return": summaries[vid]["strategy_total_return_paths"][0],
             "max_drawdown": summaries[vid]["strategy_max_drawdown_paths"][0]} for vid in results]
    if not args.synthetic:
        pd.DataFrame(rows).to_csv(args.csv, index=False)
    print(f"validate look done in {time.time() - t0:.1f}s; best {best} validate mean delta "
          f"{summaries[best]['mean_delta']:+.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
