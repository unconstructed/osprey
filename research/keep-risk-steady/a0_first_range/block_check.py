"""Diagnostic on A0's FIRST seed range only (already looked at): boundary counts by mean block length."""
import math, sys, json, time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.path.insert(0, "/home/user/osprey"); sys.path.insert(0, "/home/user/osprey/research/keep-risk-steady")
import controls as C
from lab.runner import keeprisk as K
R = C.R
BLOCKS = (60, 120, 250, 500)
_IDX = {}
def series(task):
    set_name, j = task
    ctx = C._CTX
    s, f = C.MIX
    prices, signal = C.build_panels(set_name, j, False)
    sig = K.swing(signal, f)
    out = {}
    for w in K.W_VALUES:
        full = K.q_path(signal, w, f, sigma=sig)
        rule = K.run_rule(prices, full, s, f, limits=ctx["limits"], costs=ctx["costs"])
        x = K.matched_share(s * full.q)
        xr = K.run_yardstick(prices, x, f, limits=ctx["limits"], costs=ctx["costs"])
        a, b = rule["ret"].to_numpy()[1:], xr["ret"].to_numpy()[1:]
        out[w] = {}
        for m in BLOCKS:
            rx = K.risk_x(a, b, _IDX[m], keep=True)
            out[w][m] = (rx["V"], rx["V_star"], rx["p_calm"], rx["p_eq"])
    return set_name, j, out
def init(ctx):
    C._CTX.update(ctx)
    for m in BLOCKS:
        _IDX[m] = K.index_set(2189, mean_block=m)
if __name__ == "__main__":
    t0 = time.time()
    limits = R.steady_limits(None)
    ctx = {"limits": {"min_cash": limits["min_cash"], "max_coin": limits["max_coin"]},
           "costs": R.cost_models(None)[("1x", K.DEPOSIT)]}
    todo = [(s, j) for s in ("PG", "NC", "NW") for j in range(100)]
    with ProcessPoolExecutor(4, mp_context=mp.get_context("fork"), initializer=init, initargs=(ctx,)) as pool:
        res = list(pool.map(series, todo))
    out = {}
    for m in BLOCKS:
        for s in ("PG", "NC", "NW"):
            up = lo = tests = calm = eq = 0
            rows = [r for r in res if r[0] == s]
            sds = []
            for w in K.W_VALUES:
                vs = [r[2][w][m][0] for r in rows]
                for i, r in enumerate(rows):
                    v, star, pc, pe = r[2][w][m]
                    others = [x for k, x in enumerate(vs) if k != i]
                    vbar = math.fsum(others) / len(others)
                    tests += 1
                    up += (1 + int((star >= vbar).sum())) / 10001 < 0.05
                    lo += (1 + int((star <= vbar).sum())) / 10001 < 0.05
                    calm += pc < 0.05; eq += pe < 0.05
                    sds.append(np.std(star))
            out[f"{s} block {m}"] = dict(upper=up, lower=lo, tests=tests, p_calm_lt_05=calm, p_eq_lt_05=eq,
                                         boot_sd_median=round(float(np.median(sds)), 4))
            print(s, m, out[f"{s} block {m}"], flush=True)
    json.dump(out, open(sys.argv[1], "w"), indent=1)
    print("secs", round(time.time() - t0))
