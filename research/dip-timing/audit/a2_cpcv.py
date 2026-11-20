"""Auditor check 2d: event-level CPCV purge and embargo, re-derived independently from the stored train events
(no data load). Own splitter: 6 contiguous groups over events sorted by ts0, all C(6,2) test pairs; purge any
training event whose [ts0, ts_end] meets ANY test event's [ts0, ts_end] or the test group's span; embargo
training events triggering within 31 days after a test group's last exit."""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import itertools
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, REPO + "")
from lab.models import dips  # noqa: E402

ev = pd.read_parquet(REPO + "/results/dip-timing/train/events_d0.parquet")
assert ev["ts0"].is_monotonic_increasing
EMB = pd.Timedelta(days=31)
for name, mask in (("all", np.ones(len(ev), bool)), ("funding", ev["funding_covered"].to_numpy()),
                   ("oi", ev["oi_covered"].to_numpy())):
    sub = ev.loc[mask].reset_index(drop=True)
    s0, s1 = pd.DatetimeIndex(sub["ts0"]), pd.DatetimeIndex(sub["ts_end"])
    n = len(sub)
    lab = dips.event_cpcv(sub["ts0"], sub["ts_end"], 6, 2, EMB)
    groups = np.array_split(np.arange(n), 6)
    mine = []
    for pair in itertools.combinations(range(6), 2):
        test = np.concatenate([groups[g] for g in pair])
        train = np.setdiff1d(np.arange(n), test)
        keep = np.ones(len(train), bool)
        for g in pair:
            lo, hi = s0[groups[g]].min(), s1[groups[g]].max()
            keep &= ~((s0[train] <= hi) & (s1[train] >= lo))
            keep &= ~((s0[train] > hi) & (s0[train] <= hi + EMB))
        mine.append((train[keep], test, pair))
    same = all(np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and tuple(a[2]) == tuple(b[2])
               for a, b in zip(lab, mine, strict=True))
    # strict event-level property: no kept training event overlaps any test event span; none in the embargo
    worst_gap = pd.Timedelta.max
    bad = 0
    for tr, te, pair in lab:
        for i in tr:
            ov = (s0[i] <= s1[te]) & (s1[i] >= s0[te])
            bad += int(ov.any())
            # gap between a training event and the nearest test event (either side)
            gaps = np.concatenate([(s0[te] - s1[i]).to_numpy(), (s0[i] - s1[te]).to_numpy()])
            gaps = gaps[gaps > pd.Timedelta(0)]
            worst_gap = min(worst_gap, gaps.min()) if len(gaps) else worst_gap
        for g in pair:
            hi = s1[groups[g]].max()
            bad += int(((s0[tr] > hi) & (s0[tr] <= hi + EMB)).any())
    sizes = [len(t) for t, _, _ in lab]
    purged = [n - len(te) - len(tr) for tr, te, _ in lab]
    print(f"{name:8s} n={n:3d} splits={len(lab)} same as auditor splitter: {same}; violations: {bad}; train sizes "
          f"min {min(sizes)} max {max(sizes)}; purged+embargoed per split min {min(purged)} max {max(purged)}; "
          f"closest train-test gap {worst_gap}")
    # paths: oracle (value = split index) -> path j of a group = j-th split testing it
    vals = [np.full(len(te), k, float) for k, (_, te, _) in enumerate(lab)]
    P = dips.event_paths(n, 6, 2, vals)
    ok = True
    for g in range(6):
        js = [k for k, (_, _, pair) in enumerate(lab) if g in pair]
        for j in range(P.shape[0]):
            ok &= bool((P[j, groups[g]] == js[j]).all())
    print(f"         paths {P.shape}: path j uses the j-th split testing each group: {ok}")
