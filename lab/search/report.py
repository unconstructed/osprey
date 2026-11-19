"""Overfitting report for a walk-forward search: is the winner real or luck?"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..validation import montecarlo as mc
from ..validation import stats
from .study import load_trial_returns


def overfitting_report(wf: dict, out_dir: str | Path, periods_per_year: int = 365) -> dict:
    """DSR with raw and effective trial counts, PBO per fold, Monte Carlo drawdowns."""
    oos = wf["oos_returns"].to_numpy(float)
    trial_sharpes, eff_counts, pbos = [], [], []
    for study in wf["studies"]:
        m = load_trial_returns(study, out_dir).dropna()
        if m.shape[1] < 2:
            continue
        trial_sharpes += [stats.sharpe(m[c]) for c in m.columns]
        eff_counts.append(stats.effective_trials(m.to_numpy()))
        pbos.append(stats.probability_of_backtest_overfitting(m.to_numpy(), n_blocks=10)["pbo"])
    n_raw = wf["total_trials"]
    n_eff = float(np.sum(eff_counts)) if eff_counts else 1.0
    if trial_sharpes:
        dsr_raw = stats.deflated_sharpe_ratio(oos, trial_sharpes, n_trials=n_raw)["dsr"]
        dsr_eff = stats.deflated_sharpe_ratio(oos, trial_sharpes, n_trials=n_eff)["dsr"]
    else:
        # No study kept 2+ completed trials, so the spread of trial Sharpes (the luck benchmark) is
        # unknown. DSR is missing, and a missing number fails its gate.
        dsr_raw = dsr_eff = float("nan")
    dd_block = mc.block_bootstrap_drawdowns(oos, n_sims=1000, mean_block=20)
    return {
        "oos_sharpe_annual": stats.annualized_sharpe(oos, periods_per_year),
        "oos_total_return": float(np.prod(1 + oos) - 1),
        "oos_max_drawdown": mc.max_drawdown(oos),
        "wf_efficiency": wf["wf_efficiency"],
        "trials_raw": n_raw,
        "trials_effective": n_eff,
        "dsr_raw_count": dsr_raw,
        "dsr_effective_count": dsr_eff,
        "pbo_mean": float(np.mean(pbos)) if pbos else float("nan"),
        "mc_drawdown_worst5pct": mc.percentiles(dd_block, (5,))["p5"],
        "mc_drawdown_median": mc.percentiles(dd_block, (50,))["p50"],
    }


def gates(rep: dict, budget_drawdown: float | None = None) -> dict:
    """Default validation gates from AGENTS.md (the owner can change thresholds)."""
    g = {
        "oos_sharpe >= 1.0": rep["oos_sharpe_annual"] >= 1.0,
        "dsr (effective) >= 0.95": rep["dsr_effective_count"] >= 0.95,
        "pbo <= 0.25": rep["pbo_mean"] <= 0.25,
    }
    if budget_drawdown is not None:
        g[f"MC worst-5% drawdown within {budget_drawdown:.0%}"] = rep["mc_drawdown_worst5pct"] >= -budget_drawdown
    return g
