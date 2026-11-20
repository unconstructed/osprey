"""Auditor check 4: recompute PBO, effective trials and DSR from the logged daily series, independently of
lab.validation.stats (own CSCV, own DSR formula), and compare with the lab functions and summary.json.
Reads stored train outputs only (no data loads)."""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import itertools
import json
import math
import sys

import numpy as np
import pandas as pd
from scipy import stats as sst

R = REPO + "/results/dip-timing/train/"
series = pd.read_parquet(R + "series.parquet")
summ = json.load(open(R + "summary.json"))
vids = [f"V{i:02d}" for i in range(1, 41)]
print("series shape", series.shape, "index", series.index.min(), series.index.max())
assert series.index.max() <= pd.Timestamp("2023-01-01", tz="UTC")


def sr(x):
    x = np.asarray(x, float)
    sd = x.std(ddof=1)
    return 0.0 if sd <= 1e-9 * np.abs(x).max() else x.mean() / sd


def my_pbo(m, n_blocks=10):
    t, n = m.shape
    blocks = np.array_split(np.arange(t), n_blocks)
    logits = []
    for is_b in itertools.combinations(range(n_blocks), n_blocks // 2):
        oos_b = [b for b in range(n_blocks) if b not in is_b]
        is_rows = np.concatenate([blocks[b] for b in is_b])
        oos_rows = np.concatenate([blocks[b] for b in oos_b])
        is_sr = np.array([sr(m[is_rows, j]) for j in range(n)])
        oos_sr = np.array([sr(m[oos_rows, j]) for j in range(n)])
        best = np.flatnonzero(is_sr == is_sr.max())
        star = best[np.argmin(oos_sr[best])]  # lab tie rule: worst OOS among IS ties
        rank = sst.rankdata(oos_sr, method="average")[star]
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    logits = np.array(logits)
    return float((logits <= 0).mean()), len(logits)


def my_eff(m):
    sd = m.std(axis=0, ddof=1)
    live = m[:, sd > 1e-9 * np.abs(m).max(axis=0)]
    c = np.corrcoef(live, rowvar=False)
    e = np.linalg.eigvalsh(c)
    e = e[e > 0]
    p = e / e.sum()
    return float(np.exp(-(p * np.log(p)).sum()))


def my_dsr(best, trial_sr, n):
    g = 0.5772156649
    v = np.var(trial_sr, ddof=1)
    emax = math.sqrt(v) * ((1 - g) * sst.norm.ppf(1 - 1 / n) + g * sst.norm.ppf(1 - 1 / (n * math.e)))
    emax = max(emax, 0.0)
    x = np.asarray(best, float)
    s = sr(x)
    skew = sst.skew(x)
    kurt = sst.kurtosis(x, fisher=False)
    t = len(x)
    z = (s - emax) * math.sqrt(t - 1) / math.sqrt(1 - skew * s + (kurt - 1) / 4 * s * s)
    return float(sst.norm.cdf(z)), emax, v, s


paths = []
for j in range(5):
    m = np.column_stack([series[f"{v}_path{j}"].to_numpy() for v in vids])
    p, ncomb = my_pbo(m)
    paths.append(p)
print(f"PBO per path (auditor CSCV, {ncomb} combos):", [round(x, 4) for x in paths], "mean", round(np.mean(paths), 4))
print("PBO per path (summary.json):", summ["criteria_best"]["pbo_paths"], summ["criteria_best"]["pbo"])

# median path per variant: path with the median strategy Sharpe (study.median_path)
med = {}
for v in vids:
    sh = summ["summaries"][v]["strategy_sharpe_paths"]
    j = int(np.argsort(sh, kind="stable")[len(sh) // 2])
    med[v] = series[f"{v}_path{j}"].to_numpy()
mm = np.column_stack([med[v] for v in vids])
tsr = np.array([sr(mm[:, k]) for k in range(mm.shape[1])])
neff = my_eff(mm)
best = summ["selections"]["best"]
print("best", best, "per-period Sharpe", round(sr(med[best]), 5), "annualised", round(sr(med[best]) * math.sqrt(365), 3))
print("effective trials (auditor)", round(neff, 3), "summary", round(summ["criteria_best"]["n_trials_effective"], 3))
for label, n in (("effective", neff), ("raw 40", 40), ("40 + 2 T1 reference runs", 42),
                 ("+ 10 timing-profile schedules", 52), ("x10 trials (400)", 400)):
    d, emax, v, s = my_dsr(med[best], tsr, n)
    print(f"DSR {label:32s} n={n:7.2f} emax={emax:.5f} var={v:.6f} dsr={d:.4f}")
print("summary DSR eff", summ["criteria_best"]["dsr_effective"])
print("summary DSR raw", summ["criteria_best"]["dsr_raw"])
# best by Sharpe among trials (what DSR would see if selection were by Sharpe)
k = int(np.argmax(tsr))
d, emax, v, s = my_dsr(mm[:, k], tsr, 40)
print("highest-Sharpe trial", vids[k], "ann. Sharpe", round(tsr[k] * math.sqrt(365), 3), "DSR raw 40 =", round(d, 4),
      "DSR eff =", round(my_dsr(mm[:, k], tsr, neff)[0], 4))

sys.path.insert(0, REPO + "")
from lab.validation import stats  # noqa: E402

lab_pbo = [stats.pbo(np.column_stack([series[f"{v}_path{j}"].to_numpy() for v in vids]), n_blocks=10)["pbo"]
           for j in range(5)]
print("PBO per path (lab stats.pbo):", [round(x, 4) for x in lab_pbo])
print("lab effective_trials", stats.effective_trials(mm), "lab DSR eff", stats.deflated_sharpe_ratio(
    med[best], stats.column_sharpes(mm), n_trials=stats.effective_trials(mm))["dsr"])
