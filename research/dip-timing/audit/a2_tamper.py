"""Auditor check 2: tamper the future on the REAL train bars, through the study's own pipeline.

For 25 random cut times (at random dip events, random offset 0..31 into the event), every bar of both coins
from the cut on is replaced by random-walk junk (valid OHLC). Then, everything known before the cut must be
bit-identical: events (t0, P_ref, features, positioning), day rows (all 24 model inputs), labels whose window
ends before the cut, the T1-T4 targets decided at closes before the cut, and the T5 / Q model probabilities
of models fitted on events whose labels are complete before the cut. Train closes only (<= 2023-01-01).
"""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import sys

import numpy as np

sys.path.insert(0, REPO + "/research/dip-timing")
import study as S  # noqa: E402

from lab.models import dips  # noqa: E402
from lab.models.features import compute_features  # noqa: E402
from lab.runner.reference import Costs  # noqa: E402

costs = Costs.from_yaml()
m = S.load_market("kraken", S.TRAIN_LAST_CLOSE)
assert all(b.index.max() <= S.TRAIN_LAST_CLOSE for b in m.bars.values())
es = S.build_eventset("D0", m, S.D0, costs, S.TRAIN)
ev = es.events
rng = np.random.default_rng(20261120)
RECIPES = {"V05": S.Recipe("T5", b_model="logistic"), "V06": S.Recipe("T5", b_model="lightgbm"),
           "V08": S.Recipe("T1", filter="Q"), "V12": S.Recipe("T1", filter="Q", q_extra=("funding_7d",),
                                                           subset="funding")}


def tamper(b, cut_ts, rng):
    b = b.copy()
    after = b.index >= cut_ts
    n = int(after.sum())
    if n == 0:
        return b
    f = np.exp(np.cumsum(rng.normal(0, 0.06, n)))
    c = b.loc[after, "close"].to_numpy() * f * np.exp(rng.normal(0, 0.03, n))
    o = b.loc[after, "open"].to_numpy() * f * np.exp(rng.normal(0, 0.03, n))
    hi = np.maximum(np.maximum(o, c), b.loc[after, "high"].to_numpy() * f) * np.exp(np.abs(rng.normal(0, 0.02, n)))
    lo = np.minimum(np.minimum(o, c), b.loc[after, "low"].to_numpy() * f) * np.exp(-np.abs(rng.normal(0, 0.02, n)))
    b.loc[after, ["open", "high", "low", "close"]] = np.column_stack([o, hi, lo, c])
    b.loc[after, "volume"] = b.loc[after, "volume"].to_numpy() * np.exp(rng.normal(0, 1, n))
    return b


def same(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and np.array_equal(np.isnan(a), np.isnan(b)) and np.array_equal(a[~np.isnan(a)],
                                                                                              b[~np.isnan(b)])


fails, n_checked = [], {"events": 0, "day_rows": 0, "labels": 0, "targets": 0, "probs": 0}
moved_after = 0
for trial in range(25):
    e = int(rng.integers(len(ev)))
    coin = ev.at[e, "coin"]
    pos = int(ev.at[e, "t0"]) + int(rng.integers(0, 32))
    cut_ts = m.bars[coin].index[pos]
    bars2 = {c: tamper(m.bars[c], cut_ts, rng) for c in S.COINS}
    m2 = S.Market("tampered", bars2, {c: compute_features(bars2[c]) for c in S.COINS}, m.funding, m.pos,
                  m.snapshot, m.last_close)
    es2 = S.build_eventset("D0", m2, S.D0, costs, S.TRAIN)
    ev2 = es2.events
    pre = ev.index[ev["ts0"] < cut_ts]
    pre2 = ev2.index[ev2["ts0"] < cut_ts]
    cols = ["t0", "ref_bar", "p_ref", "q_speed", "q_ma_dist_100", "q_vol_ratio_10_60", "ewma_vol_20", "funding_7d",
            "oi_chg_dip"]
    ok_ev = list(pre) == list(pre2) and all(same(ev.loc[pre, c], ev2.loc[pre2, c]) for c in cols) and \
        list(ev.loc[pre, "coin"]) == list(ev2.loc[pre2, "coin"])
    n_checked["events"] += len(pre)
    # day rows decided before the cut (close of d < cut)
    def day_ts(frame, evs):
        return np.array([es.market.bars[c].index[int(d)] for c, d in zip(frame["coin"], frame["d"], strict=True)])
    dts = day_ts(es.days, ev)
    rows = (es.days["event"].isin(pre)) & (dts < cut_ts)
    dts2 = np.array([bars2[c].index[int(d)] for c, d in zip(es2.days["coin"], es2.days["d"], strict=True)])
    rows2 = (es2.days["event"].isin(pre2)) & (dts2 < cut_ts)
    feat_cols = list(dips.B_FEATURES) + list(S.FEATURES) + list(dips.Q_FEATURES) + ["funding_7d"]
    ok_days = rows.sum() == rows2.sum() and all(same(es.days.loc[rows, c], es2.days.loc[rows2, c]) for c in feat_cols)
    n_checked["day_rows"] += int(rows.sum())
    # labels whose window ends before the cut: y_B (lows d+1..d+10), r_T1 / y_Q (exit open of end_bar)
    lab_rows = rows & np.array([m.bars[c].index[min(int(d) + 10, len(m.bars[c]) - 1)] < cut_ts
                                for c, d in zip(es.days["coin"], es.days["d"], strict=True)])
    lab_rows2 = rows2 & np.array([bars2[c].index[min(int(d) + 10, len(bars2[c]) - 1)] < cut_ts
                                  for c, d in zip(es2.days["coin"], es2.days["d"], strict=True)])
    done = ev.index[ev["ts_end"] < cut_ts]
    done2 = ev2.index[ev2["ts_end"] < cut_ts]
    ok_lab = same(es.days.loc[lab_rows, "y_B"], es2.days.loc[lab_rows2, "y_B"]) and \
        same(ev.loc[done, "r_T1"], ev2.loc[done2, "r_T1"])
    n_checked["labels"] += int(lab_rows.sum()) + len(done)
    # rule targets decided at closes before the cut
    ok_tg = True
    for i in pre:
        c = ev.at[i, "coin"]
        t0 = int(ev.at[i, "t0"])
        k = int(np.searchsorted(m.bars[c].index, cut_ts)) - t0  # number of decision closes before the cut
        for rule in ("T1", "T2", "T3", "T4"):
            p1, _ = S.rule_plan(es, int(i), rule)
            p2, _ = S.rule_plan(es2, int(i), rule)
            a = dips.event_targets(m.bars[c], t0, p1, S.D0)[0][: max(k, 0)]
            b = dips.event_targets(bars2[c], t0, p2, S.D0)[0][: max(k, 0)]
            ok_tg &= np.array_equal(a, b)
            n_checked["targets"] += 1
    # models fitted on events whose labels are complete before the cut, applied to day rows before the cut
    ok_p = True
    if len(done) >= 10:
        for rec in RECIPES.values():
            sub = S.subset_of(es, rec)
            tr = np.intersect1d(sub, done)
            te = np.intersect1d(sub, pre)
            if len(tr) < 6 or len(np.unique(ev.loc[tr, "y_Q"])) < 2 or len(te) == 0:
                continue
            d1 = S.decide(es, rec, S.fit_models(es, rec, tr), te)
            d2 = S.decide(es2, rec, S.fit_models(es2, rec, tr), te)
            if "p_q" in d1:
                ok_p &= np.array_equal(d1["p_q"], d2["p_q"])
            if "p_b" in d1:
                r1 = (es.days["event"].isin(te)).to_numpy()
                keep = (dts[r1] < cut_ts)
                ok_p &= np.array_equal(d1["p_b"][keep], d2["p_b"][keep])
            n_checked["probs"] += 1
    # power: something after the cut really changed
    moved_after += int(not same(m.bars[coin]["close"].iloc[pos:], bars2[coin]["close"].iloc[pos:]))
    status = all((ok_ev, ok_days, ok_lab, ok_tg, ok_p))
    if not status:
        fails.append((trial, str(cut_ts), ok_ev, ok_days, ok_lab, ok_tg, ok_p))
    print(f"cut {cut_ts.date()} ({coin} event {e} +{pos - int(ev.at[e, 't0'])}): events {ok_ev} day rows {ok_days} "
          f"labels {ok_lab} targets {ok_tg} model probs {ok_p}; events after cut before/after tamper "
          f"{len(ev) - len(pre)}/{len(ev2) - len(pre2)}")
print("checked", n_checked, "tampers that moved later bars:", moved_after, "of 25")
print("FAILURES:", fails)
