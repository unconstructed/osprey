"""Finalization checks for the dip-timing study after the audit (RESULTS.md, section "Audit fixes").

SCOUTING ONLY: every profit number is from the reference backtester, not NautilusTrader (AGENTS.md hard rule 3).

What this does and does not do:
- Reads the stored TRAIN outputs only (results/dip-timing/train) and config/costs.yaml. It loads no bars and no
  positioning data, and reads nothing of the validate look or the test window.
- Runs no variant and adds no trial (the trial count stays 40). It recomputes, with the lab's own functions and
  the study's own bootstrap stream (seed 0, 10,000 draws), the numbers that the corrected wording in RESULTS.md
  quotes: the round-trip cost (audit F1), the lower tail of the primary-family bootstrap (F2), the 80%-power
  range (F9), the DSR with the uncounted configurations added to the count (F5) and where T1's train mean comes
  from (F7).
- Refuses to run if the frozen code, config or train outputs differ from results/dip-timing/FROZEN.json.

    uv run python research/dip-timing/final_checks.py
"""

from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import pandas as pd
import study as S

from lab.models import dips
from lab.runner.reference import Costs, scheduled
from lab.validation import stats

TRAIN_DIR = S.REPO / "results/dip-timing/train"
TRAIN_CUT = pd.Timestamp("2023-01-01", tz="UTC")  # the last train close (day 2022-12-31 closes here)
PRIMARY = [f"V{i:02d}" for i in range(2, 11)]


def check_frozen() -> dict:
    frozen = json.loads((S.REPO / "results/dip-timing/FROZEN.json").read_text())
    outputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(TRAIN_DIR.iterdir()) if p.is_file()}
    ok = (frozen["config_hash"] == S.config_hash() and frozen["code_hashes"] == S.code_hashes()
          and frozen["train_outputs_sha256"] == outputs)
    if not ok:
        raise SystemExit("code, config or train outputs differ from FROZEN.json: nothing is recomputed")
    return frozen


def round_trip_cost() -> dict:
    """One full round trip of a fresh USD 10,000 sleeve at a flat price, through the engine."""
    idx = pd.date_range("2020-01-02", periods=5, freq="D", tz="UTC", name="ts")
    bars = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}, index=idx)
    bars["w"] = [1.0, 0.0, 0.0, 0.0, 0.0]  # buy at the open of bar 1, sell at the open of bar 2
    out = {}
    for k in (1.0, 2.0):
        costs = Costs.from_yaml() if k == 1.0 else Costs.from_yaml().stressed(k)
        res = scheduled({"col": "w"}, bars, costs)
        out[f"{k:g}x"] = float(1.0 - (1.0 + res["ret"]).prod())
    c = Costs.from_yaml()
    out["per_leg_additive"] = c.rate(10_000.0) + c.gas_fraction(10_000.0)
    return out


def bootstrap_tails(events: pd.DataFrame, summary: dict) -> dict:
    """The study's month bootstrap (same seed and draws), both tails, for V02-V10 against T1."""
    months = events["month"].to_numpy()
    out = {}
    for v in PRIMARY:
        delta = (events[f"r_{v}"] - events["r_T1"]).to_numpy()
        lab = dips.month_bootstrap(delta, months, S.N_BOOT, S.SEED)
        # the same draws as dips.month_bootstrap, kept here to read the lower tail too
        uniq, inv = np.unique(months, return_inverse=True)
        sums = np.bincount(inv, weights=delta, minlength=len(uniq))
        counts = np.bincount(inv, minlength=len(uniq)).astype(float)
        draw = np.random.default_rng(S.SEED).integers(0, len(uniq), size=(S.N_BOOT, len(uniq)))
        boot = sums[draw].sum(axis=1) / counts[draw].sum(axis=1)
        mean = float(delta.mean())
        p_upper = float((1 + np.sum(boot - mean >= mean)) / (S.N_BOOT + 1))
        p_lower = float((1 + np.sum(boot - mean <= mean)) / (S.N_BOOT + 1))
        assert p_upper == lab["p"], (v, p_upper, lab["p"])
        out[v] = {"mean": mean, "p_upper": p_upper, "p_upper_study": summary["summaries"][v]["p_boot"],
                  "p_lower": p_lower, "ci": [lab["ci_low"], lab["ci_high"]],
                  "power_pct": summary["summaries"][v]["power_threshold_pct"]}
    lower = dips.holm([out[v]["p_lower"] for v in PRIMARY])
    upper = dips.holm([out[v]["p_upper"] for v in PRIMARY])
    for v, lo, up in zip(PRIMARY, lower, upper, strict=True):
        out[v]["holm_lower"], out[v]["holm_upper"] = float(lo), float(up)
    return out


def dsr_counts(summary: dict) -> dict:
    """DSR of the best variant's median-path series with the raw count 40, 42 (+ the two T1 reference runs) and
    52 (+ the 10 fixed-day timing schedules), and with the effective count. The 12 extra configurations have no
    stored series, so only the count changes; the trial-Sharpe variance is that of the 40 logged trials."""
    series = pd.read_parquet(TRAIN_DIR / "series.parquet")
    assert series.index.max() <= TRAIN_CUT, series.index.max()
    vids = [f"V{i:02d}" for i in range(1, 41)]
    med = {}
    for v in vids:
        sharpes = summary["summaries"][v]["strategy_sharpe_paths"]
        j = int(np.argsort(sharpes, kind="stable")[len(sharpes) // 2])  # study.median_path
        med[v] = series[f"{v}_path{j}"].fillna(0.0).to_numpy()
    matrix = np.column_stack([med[v] for v in vids])
    trial_sharpes = stats.column_sharpes(matrix)
    best = summary["criteria_best"]["best"]
    n_eff = stats.effective_trials(matrix)
    out = {"best": best, "n_effective": float(n_eff)}
    for label, n in (("effective", max(n_eff, 1.0)), ("raw_40", 40), ("raw_42", 42), ("raw_52", 52)):
        d = stats.deflated_sharpe_ratio(med[best], trial_sharpes, n_trials=n)
        out[label] = {"dsr": float(d["dsr"]), "expected_max_sharpe": float(d["expected_max_sharpe"])}
    assert out["raw_40"]["dsr"] == summary["criteria_best"]["dsr_raw"]["dsr"]
    assert out["effective"]["dsr"] == summary["criteria_best"]["dsr_effective"]["dsr"]
    return out


def t1_concentration(events: pd.DataFrame) -> dict:
    r = events["r_T1"]
    year = events["month"].str[:4]
    by_year = {y: {"n": int((year == y).sum()), "mean": float(r[year == y].mean())} for y in sorted(year.unique())}
    top3 = r.sort_values(ascending=False).index[:3]
    return {
        "mean": float(r.mean()),
        "median": float(r.median()),
        "by_year": by_year,
        "mean_without_2017": float(r[year != "2017"].mean()),
        "n_without_2017": int((year != "2017").sum()),
        "mean_without_top3": float(r.drop(top3).mean()),
        "top3": [float(x) for x in r.loc[top3]],
        "top_event": {"coin": events.loc[top3[0], "coin"], "trigger_month": events.loc[top3[0], "month"],
                      "r_T1": float(r.loc[top3[0]])},
    }


def auc_mean(fq: dict) -> float:
    """Mean out-of-sample AUC over the CPCV splits that have both classes (a split without one is stored as None)."""
    values = [x for x in (fq["b_auc"] or fq["q_auc"]) if x is not None]
    return float(np.mean(values))


def main() -> int:
    frozen = check_frozen()
    summary = json.loads((TRAIN_DIR / "summary.json").read_text())
    events = pd.read_parquet(TRAIN_DIR / "events_d0.parquet")
    assert pd.to_datetime(events["ts_end"]).max() <= TRAIN_CUT
    assert len(events) == 80 and summary["n_trials_logged"] == 40
    out = {
        "label": S.LABEL,
        "config_hash": frozen["config_hash"],
        "trials_logged": summary["n_trials_logged"],
        "round_trip_cost_usd_10000": round_trip_cost(),
        "primary_bootstrap": bootstrap_tails(events, summary),
        "dsr": dsr_counts(summary),
        "t1_train": t1_concentration(events),
        "power_range_pct": [min(summary["summaries"][v]["power_threshold_pct"] for v in PRIMARY),
                            max(summary["summaries"][v]["power_threshold_pct"] for v in PRIMARY)],
        "auc_mean": {v: auc_mean(summary["forecast_quality"][v]) for v in sorted(summary["forecast_quality"])},
    }
    json.dump(S.jsonable(out), sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
