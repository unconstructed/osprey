"""End-to-end demo: prediction models + smart search + overfitting checks.

Runs on SYNTHETIC data (no network needed). The numbers prove the pipeline works and
show what the checks catch; they are not evidence about real markets. On real data,
replace `load_bars()` with the catalog loader from milestone 1.

    uv run python scripts/demo.py --trials 150 --workers 4

Merged into osprey from the starter: it runs on osprey's kept modules (reference runner with fills at the next
open and the costs.yaml cost model, per-bar volatility features and labels). --results-dir and --report-dir
choose where trial files and the report go (defaults: results/demo and reports/demo).
"""

from __future__ import annotations

import argparse
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.synthetic import synthetic_market
from lab.models import baselines, labels
from lab.models.artifact import save_model, train_final
from lab.models.features import FEATURES
from lab.models.features import compute_features as build_features
from lab.models.train import cpcv_evaluate, summarize, walk_forward_predict
from lab.runner.reference import PERIODS_PER_YEAR, Costs, buy_and_hold, constant_mix, dip_buy
from lab.search.report import gates, overfitting_report
from lab.search.space import Param
from lab.search.study import SearchConfig
from lab.search.walkforward import walk_forward_optimize
from lab.validation import montecarlo as mc
from lab.validation.splits import walk_forward
from lab.validation.stats import annualized_sharpe

SEARCH_END = "2024-06-30"  # train + validate; the test window after this stays untouched

SPECS = [  # osprey dip_buy names; drop and stop are fractions
    Param("drop", "float", 0.03, 0.25),
    Param("lookback", "int", 2, 20),
    Param("hold", "int", 3, 40),
    Param("stop", "float", 0.03, 0.25),
]
SPECS_VT = SPECS + [Param("vol_target", "float", 0.2, 1.0)]
EWMA = "EWMA (span 20)"


def dip_buy_model_vol(params: dict, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Dip buy sized by the model's annualised volatility forecast in bars["pred_vol"]."""
    return dip_buy({**params, "vol_col": "pred_vol"}, bars, costs)


def load_bars(seed: int = 7) -> pd.DataFrame:
    return synthetic_market(3400, seed=seed, start="2017-01-01")["BTC"].loc[:SEARCH_END].copy()


def shuffled_control(bars: pd.DataFrame, seed: int = 99) -> pd.DataFrame:
    """Same daily moves in random order: no regimes, no volatility clusters, no edge."""
    rng = np.random.default_rng(seed)
    lr = np.log(bars["close"]).diff().fillna(0).to_numpy()
    perm = rng.permutation(len(lr))
    close = bars["close"].iloc[0] * np.exp(np.cumsum(lr[perm]))
    span = (bars["high"] / bars["low"]).to_numpy()[perm]
    out = pd.DataFrame(index=bars.index)
    out["close"] = close
    out["open"] = np.concatenate([[close[0]], close[:-1]])
    out["high"] = np.maximum(out["open"], out["close"]) * np.sqrt(span)
    out["low"] = np.minimum(out["open"], out["close"]) / np.sqrt(span)
    out["volume"] = bars["volume"].to_numpy()[perm]
    return out


def doubled_cost_oos(wf: dict, bars: pd.DataFrame, backtest_fn=dip_buy, warmup: int = 120) -> pd.Series:
    """Re-run each fold's chosen parameters on its test block with costs doubled."""
    parts = []
    for _, row in wf["folds"].iterrows():
        params = {k[2:]: v for k, v in row.items() if k.startswith("p_")}
        test = bars.loc[str(row.test_start) : str(row.test_end)]
        start = max(0, bars.index.get_loc(test.index[0]) - warmup)
        ctx = bars.iloc[start : bars.index.get_loc(test.index[-1]) + 1]
        res = backtest_fn(params, ctx, Costs.from_yaml().stressed(2.0))
        part = res["ret"].loc[test.index[0] :].iloc[1:]
        part.attrs = {}  # the runner's attrs (arrays, frames) would make pd.concat raise
        parts.append(part)
    return pd.concat(parts)


def fmt(x, pct=False, nd=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.1%}" if pct else f"{x:.{nd}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=150, help="Optuna trials per walk-forward fold")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--results-dir", default="results/demo", help="trial files, journals and the saved model")
    ap.add_argument("--report-dir", default="reports/demo", help="where the markdown report is written")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.results_dir)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    bars = load_bars()
    X = build_features(bars)

    # ---------- 1. Prediction models vs. baselines (CPCV) ----------
    vol_results = {}
    for h in (5, 20):
        y = labels.forward_vol(bars, h)
        res = cpcv_evaluate(
            X, y, "vol", horizon=h,
            baselines={
                f"naive (last {h} days)": baselines.naive_vol(bars, h),
                "long-run (60 days)": baselines.naive_vol(bars, 60),
                EWMA: X["ewma_vol_20"],
            },
        )
        q = res.pivot(index="split", columns="forecaster", values="qlike")
        vol_results[h] = {
            "summary": summarize(res)[["qlike_mean", "qlike_std", "rmse_log_mean", "corr_log_mean"]],
            "beats_all": float((q["model"] < q.drop(columns="model").min(axis=1)).mean()),
            "beats_ewma": float((q["model"] < q[EWMA]).mean()),
        }
    y_reg = labels.forward_regime(bars, 20)
    reg_cv = cpcv_evaluate(
        X, y_reg, "classification", horizon=20,
        baselines={"persistence (last 20 days)": X["eff_ratio_20"]},  # continuous score, so AUC is meaningful
    )

    # Use the horizon that beat its baselines; produce production-style forecasts
    use_h = max(vol_results, key=lambda h: vol_results[h]["beats_ewma"])
    y_vol = labels.forward_vol(bars, use_h)
    pred = walk_forward_predict(X, y_vol, "vol", horizon=use_h, min_train=730, retrain_every=90)
    bars["pred_vol"] = pred * np.sqrt(PERIODS_PER_YEAR)  # per-bar forecast -> annualised, like vol_target
    model, Xa = train_final("vol", X, y_vol)
    meta = save_model(
        model, out / "models" / f"vol_{use_h}d", kind="vol", target=y_vol.name, horizon=use_h,
        features=list(FEATURES), train_start=Xa.index[0], train_end=Xa.index[-1],
        data_snapshot="synthetic-seed-7", notes="demo only",
    )

    # ---------- 2. Smart search, walk-forward ----------
    folds = walk_forward(len(bars), train_size=730, test_size=365, expanding=True)
    cfg = SearchConfig(n_trials=args.trials, n_workers=args.workers, seed=0)
    ctx = {"data_snapshot": "synthetic-seed-7"}
    wf_plain = walk_forward_optimize("dip_plain", dip_buy, SPECS, bars, folds, out, cfg, context=ctx)
    wf_vt = walk_forward_optimize("dip_voltarget", dip_buy_model_vol, SPECS_VT, bars, folds, out, cfg, context=ctx)
    rep_plain = overfitting_report(wf_plain, out)
    rep_vt = overfitting_report(wf_vt, out)
    stress_plain = annualized_sharpe(doubled_cost_oos(wf_plain, bars))
    stress_vt = annualized_sharpe(doubled_cost_oos(wf_vt, bars, dip_buy_model_vol))

    # Luck control: same search on shuffled data
    noise = shuffled_control(bars)
    noise_folds = walk_forward(len(noise), train_size=730, test_size=365, expanding=True)[:3]
    wf_noise = walk_forward_optimize(
        "dip_noise", dip_buy, SPECS, noise, noise_folds, out, replace(cfg, seed=7), context=ctx
    )
    rep_noise = overfitting_report(wf_noise, out)
    best_is_noise = max(wf_noise["folds"]["is_sharpe"])

    # Benchmarks on the same out-of-sample dates
    idx = wf_plain["oos_returns"].index
    bh = buy_and_hold({}, bars)["ret"].reindex(idx).fillna(0)
    mix = constant_mix({"weight": 0.5, "every": 30}, bars)["ret"].reindex(idx).fillna(0)  # 50/50 monthly

    # ---------- 3. Report ----------
    def strat_row(name, rep, stress):
        return (
            f"| {name} | {fmt(rep['oos_sharpe_annual'])} | {fmt(rep['oos_total_return'], True)} | "
            f"{fmt(rep['oos_max_drawdown'], True)} | {fmt(stress)} | {fmt(rep['wf_efficiency'])} | "
            f"{rep['trials_raw']} / {rep['trials_effective']:.0f} | {fmt(rep['dsr_effective_count'])} | "
            f"{fmt(rep['pbo_mean'])} | {fmt(rep['mc_drawdown_worst5pct'], True)} |"
        )

    def bench_row(name, r):
        return (
            f"| {name} | {fmt(annualized_sharpe(r))} | {fmt(float(np.prod(1 + r) - 1), True)} | "
            f"{fmt(mc.max_drawdown(r), True)} | — | — | — | — | — | — |"
        )

    reg_sum = summarize(reg_cv)[["auc_mean", "auc_std"]]
    vol_lines = []
    for h, v in vol_results.items():
        vol_lines += [
            f"**Next-{h}-day volatility** (QLIKE and RMSE: lower is better; correlation: higher is better)",
            "",
            v["summary"].round(3).to_markdown(),
            "",
            f"Model beat EWMA in {v['beats_ewma']:.0%} of splits and every baseline in {v['beats_all']:.0%}.",
            "",
        ]
    gp, gv = gates(rep_plain, 0.5), gates(rep_vt, 0.5)

    lines = [
        f"# Demo report: prediction models + smart search ({date.today()})",
        "",
        "> **Synthetic data.** These numbers show the pipeline working and what the checks catch.",
        "> They say nothing about real markets. Rerun on real data after milestone 1.",
        "",
        f"Search window: {bars.index[0].date()} → {bars.index[-1].date()} (train + validate). "
        f"Test window untouched. Runtime {time.time() - t0:.0f}s, {args.trials} trials per fold, "
        f"{len(folds)} walk-forward folds.",
        "",
        "## 1. Prediction models vs. baselines (CPCV, 15 purged splits)",
        "",
        *vol_lines,
        "**Next-20-day regime: trending vs. sideways** (AUC: 0.5 = coin flip)",
        "",
        reg_sum.round(3).to_markdown(),
        "",
        f"Strategies below use the {use_h}-day volatility forecast (the horizon where the model beat EWMA most). "
        f"Saved artifact: `results/demo/models/vol_{use_h}d` (sha256 {meta['model_sha256'][:12]}…).",
        "",
        "## 2. Walk-forward search: dip buying, plain vs. sized by forecast volatility",
        "",
        "| Strategy | OOS Sharpe | OOS return | Max DD | Sharpe, 2× costs | WF efficiency | Trials raw / effective | DSR | PBO | MC worst-5% DD |",
        "|---|---|---|---|---|---|---|---|---|---|",
        strat_row("Dip buy, plain", rep_plain, stress_plain),
        strat_row("Dip buy, vol-targeted by model", rep_vt, stress_vt),
        bench_row("Buy and hold", bh.to_numpy()),
        bench_row("50/50 coin/cash, monthly", mix.to_numpy()),
        "",
        "Chosen parameters per fold (plain):",
        "",
        wf_plain["folds"].drop(columns=["study"]).round(2).to_markdown(index=False),
        "",
        "Chosen parameters per fold (vol-targeted):",
        "",
        wf_vt["folds"].drop(columns=["study"]).round(2).to_markdown(index=False),
        "",
        "## 3. Luck control: the same search on shuffled data",
        "",
        f"Shuffling the daily moves destroys every real pattern. The search still found an in-sample "
        f"Sharpe of {best_is_noise:.2f}. Out of sample: Sharpe {fmt(rep_noise['oos_sharpe_annual'])}, "
        f"DSR {fmt(rep_noise['dsr_effective_count'])}, PBO {fmt(rep_noise['pbo_mean'])}. "
        "This is what a false winner looks like, and why the gates exist.",
        "",
        "## 4. Validation gates (defaults from AGENTS.md; drawdown budget 50% for illustration)",
        "",
        "| Gate | Plain | Vol-targeted |",
        "|---|---|---|",
        *[f"| {k} | {'PASS' if gp[k] else 'FAIL'} | {'PASS' if gv[k] else 'FAIL'} |" for k in gp],
        "",
    ]
    path = report_dir / f"{date.today()}.md"
    path.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nReport written to {path}")


if __name__ == "__main__":
    main()
