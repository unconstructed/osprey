"""Auditor check 6 (and 7): recompute RESULTS.md claims from the stored outputs with independent code.
No data load; stored train and validate outputs only."""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

R = REPO + "/results/dip-timing/"
ev = pd.read_parquet(R + "train/events_d0.parquet")
summ = json.load(open(R + "train/summary.json"))
look = json.load(open(R + "validate/look.json"))
va = pd.read_parquet(R + "validate/events.parquet")
S = summ["summaries"]


def boot(delta, months, draws=10_000, seed=12345):
    """Own month-block bootstrap (different RNG stream from the study), shifted one-sided p."""
    rng = np.random.default_rng(seed)
    um = np.unique(months)
    by = {m: delta[months == m] for m in um}
    means = np.empty(draws)
    for k in range(draws):
        pick = rng.choice(um, size=len(um), replace=True)
        x = np.concatenate([by[m] for m in pick])
        means[k] = x.mean()
    mu = delta.mean()
    return mu, (1 + np.sum(means - mu >= mu)) / (draws + 1), np.quantile(means, [0.025, 0.975]), \
        (1 + np.sum(means - mu <= mu)) / (draws + 1)


def holm(p):
    p = np.asarray(p)
    o = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    run = 0.0
    for r, i in enumerate(o):
        run = max(run, (m - r) * p[i])
        adj[i] = min(1.0, run)
    return adj


months = ev["month"].to_numpy()
print("== primary family V02-V10 vs T1 (path-mean per-event deltas)")
ps, lower = [], []
for i in range(2, 11):
    v = f"V{i:02d}"
    d = ev[f"r_{v}"].to_numpy() - ev["r_V01"].to_numpy()
    mu, p, ci, p_low = boot(d, months)
    ps.append(p)
    lower.append(p_low)
    print(f"{v}: mean delta {mu:+.4%} (study {S[v]['mean_delta']:+.4%}); auditor p {p:.4f} (study "
          f"{S[v]['p_boot']:.4f}); CI {ci[0]:+.2%}..{ci[1]:+.2%} (study {S[v]['delta_ci'][0]:+.2%}.."
          f"{S[v]['delta_ci'][1]:+.2%}); sd {d.std(ddof=1):.4%}; 80%-power {2.5 * d.std(ddof=1) / np.sqrt(80):.2%}; "
          f"lower-tail p {p_low:.4f}")
print("auditor Holm:", np.round(holm(ps), 4), "study Holm:", [round(summ["criteria_primary"][f"V{i:02d}"]["p_holm"], 4)
                                                          for i in range(2, 11)])
print("Holm of the LOWER-tail p (is any rule significantly WORSE than T1?):", np.round(holm(lower), 4))
print("study raw p -> Holm by auditor code:", np.round(holm([summ["criteria_primary"][f"V{i:02d}"]["p_raw"]
                                                             for i in range(2, 11)]), 4))

print("\n== V06 near-T1")
diff = ~np.isclose(ev["r_V06"], ev["r_V01"], rtol=0, atol=1e-12)
print("events where V06 path-mean result differs from T1:", int(diff.sum()), "of", len(ev))
print("forced share V06", S["V06"]["forced_share"], "sd delta V02..V06", {f"V{i:02d}": round(S[f"V{i:02d}"]["sd_delta"] * 100, 2)
                                                                          for i in range(2, 7)})
print("T1 mean r_e", ev["r_V01"].mean(), "win", (ev["r_V01"] > 0).mean())

print("\n== nulls and criteria 3")
for k, v in summ["nulls"].items():
    print(k, {kk: round(vv * 100, 2) for kk, vv in v.items()})
print({v: (round(S[v]["mean_r"] * 100, 2), summ["criteria_primary"][v]["c3"]) for v in summ["criteria_primary"]})

print("\n== positioning pairs (own bootstrap)")
ps2 = []
for a, b, sub in (("V12", "V11", "funding_covered"), ("V14", "V13", "funding_covered"), ("V16", "V15", "oi_covered")):
    msk = ev[sub].to_numpy(bool)
    d = (ev.loc[msk, f"r_{a}"] - ev.loc[msk, f"r_{b}"]).to_numpy()
    mu, p, ci, _ = boot(d, months[msk])
    ps2.append(p)
    t1 = ev.loc[msk, "r_V01"].mean()
    print(f"{a} vs {b}: n {msk.sum()} months {len(np.unique(months[msk]))} delta {mu:+.2%} p {p:.4f} "
          f"CI {ci[0]:+.2%}..{ci[1]:+.2%}; T1 on subset {t1:+.2%}")
print("Holm", np.round(holm(ps2), 4), "study", [round(t["p_holm"], 4) for t in summ["positioning_value"]])

print("\n== timing profile, hindsight")
print("train by offset", [round(x * 100, 2) for x in summ["by_offset"]["mean_r"]])
print("validate by offset", [round(x * 100, 2) for x in look["by_offset_mean_r"]])
print("hindsight", {k: round(v * 100, 2) for k, v in summ["hindsight"].items()})
bo = summ["by_offset"]["mean_r"]
w_tr = (bo[0] - bo[9]) / 9 * 100
w_va = (look["by_offset_mean_r"][0] - look["by_offset_mean_r"][9]) / 9 * 100
print(f"cost per day of waiting, train (day0-day9)/9 = {w_tr:.3f} pts; validate {w_va:.3f} pts")

print("\n== validate look")
print(va[["coin", "ts0", "r_T1", "r_V08", "funding_7d", "oi_chg_dip"]].to_string())
print("T1 mean", va["r_T1"].mean(), "winners", int((va["r_T1"] > 0).sum()), "of", len(va))
fit = look["fits"]["V08"][0]
p_q = np.array(fit["p_q"])
print("V08 theta", fit["theta_q"], "p_q range", p_q.min(), p_q.max(), "take", fit["take"])
print("V08 AUC (sklearn)", roc_auc_score(va["y_Q"], p_q), "study", look["summaries"]["V08"]["q_auc_mean"])
skipped = va.loc[~np.array(fit["take"], bool), "r_T1"]
print("skipped by Q:", len(skipped), "winners among them", int((skipped > 0).sum()), "range of winners",
      skipped[skipped > 0].min(), skipped[skipped > 0].max())
print("taken by Q:", va.loc[np.array(fit["take"], bool), ["coin", "ts0", "r_T1"]].to_dict("records"))
for v in ("V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V12", "V13", "V14", "V15", "V16"):
    d = (va[f"r_{v}"] - va["r_V01"]).mean()
    print(v, f"validate delta {d:+.2%} (study {look['summaries'][v]['mean_delta']:+.2%})", end="; ")
print()
print("criterion_7", look["criterion_7"], "benchmarks", {k: {kk: round(vv, 4) for kk, vv in v.items()}
                                                         for k, v in look["benchmarks"].items()})
print("validate T1 strategy", {k: look["summaries"]["V01"][k] for k in ("strategy_sharpe_paths",
                                                                        "strategy_total_return_paths",
                                                                        "strategy_max_drawdown_paths")})
print("validate nulls", look["nulls"])

print("\n== criteria for best and verdict")
cb = summ["criteria_best"]
print({k: cb[k] for k in ("best", "c4_delta_costs_2x", "c4", "c5_cells_positive", "c5", "c6_paths_above_t1", "c6", "pbo")})
print("c5 cells", {k: round(v * 100, 2) for k, v in cb["c5_cell_delta"].items()})
print("selections", summ["selections"])
print("passing 1-3:", [v for v, c in summ["criteria_primary"].items() if c["passes_1_3"]])
print("benchmarks train", summ["benchmarks"])
