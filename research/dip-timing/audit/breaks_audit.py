"""Auditor hand-breaks NOT in the researcher's list, applied to a scratch COPY of lab/ (the repo is untouched),
each run against tests/test_dips.py (and the contract/rules tests for reference.py)."""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import os
import shutil
import subprocess
import sys
import tempfile

M = tempfile.mkdtemp(prefix="dip_audit_breaks_")
for _d in ("lab", "tests", "config"):
    shutil.copytree(f"{REPO}/{_d}", f"{M}/{_d}", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copy(f"{REPO}/pyproject.toml", M)
PY = sys.executable
SRC = f"{M}/lab/models/dips.py"
ORIG = open(SRC).read()
breaks = {
    "Q feature ma_dist_100 read one bar late (t0+1)": (
        'out["q_ma_dist_100"] = feats["ma_dist_100"].to_numpy()[t0]',
        'out["q_ma_dist_100"] = feats["ma_dist_100"].to_numpy()[np.minimum(t0 + 1, len(feats) - 1)]'),
    "oi_chg_dip reads the open interest of the bar after t0": (
        "ok = np.isfinite(oi[t0]) & np.isfinite(oi[ref]) & (oi[t0] > 0) & (oi[ref] > 0)",
        "t0 = np.minimum(t0 + 1, len(oi) - 1)\n    ok = np.isfinite(oi[t0]) & np.isfinite(oi[ref]) & (oi[t0] > 0) & (oi[ref] > 0)"),
    "b_depth reads the next close": (
        '"b_depth": log_array(close[d] / p_ref)',
        '"b_depth": log_array(close[np.minimum(d + 1, len(close) - 1)] / p_ref)'),
    "embargo applied before the test group instead of after": (
        "embargoed = (start[train_idx] > hi) & (start[train_idx] <= hi + embargo)",
        "embargoed = (end[train_idx] < lo) & (end[train_idx] >= lo - embargo)"),
    "exit one bar early (span = hold)": (
        "return self.hold + 1", "return self.hold"),
    "day-row features of the 15 lab features at d+1": (
        "block[list(FEATURES)] = fmat[d]", "block[list(FEATURES)] = fmat[np.minimum(d + 1, len(fmat) - 1)]"),
    "T4 mean includes today": (
        "prev = sliding_window_view(rng[:-1], RANGE_LOOKBACK).mean(axis=1)",
        "prev = sliding_window_view(rng[1:], RANGE_LOOKBACK).mean(axis=1)"),
}
env = dict(os.environ, PYTHONPATH=M)
for name, (a, b) in breaks.items():
    assert ORIG.count(a) == 1, name
    open(SRC, "w").write(ORIG.replace(a, b))
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "4", "tests/test_dips.py"],
                       cwd=M, capture_output=True, text=True, env=env)
    last = [ln for ln in r.stdout.splitlines() if " passed" in ln or " failed" in ln][-1:]
    print(f"{name}: {'CAUGHT' if r.returncode else 'NOT CAUGHT'} {last}")
open(SRC, "w").write(ORIG)
r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "4", "tests/test_dips.py"], cwd=M,
                   capture_output=True, text=True, env=env)
print("restored copy:", [ln for ln in r.stdout.splitlines() if "passed" in ln][-1:])
assert open(SRC).read() == open(REPO + "/lab/models/dips.py").read()
shutil.rmtree(M, ignore_errors=True)
