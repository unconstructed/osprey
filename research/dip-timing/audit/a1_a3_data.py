"""Auditor checks 1, 2 (external alignment) and 3 (costs, fills) on the real catalog.

Data reads: TRAIN closes only (<= 2023-01-01 00:00 UTC) for every number computed here. The validate-cut
loads in part A print only index bounds and row counts (no prices, returns or outcomes).
"""
# ruff: noqa: E402  (scripts: imports follow the sys.path set-up)
from pathlib import Path as _P

REPO = str(_P(__file__).resolve().parents[3])  # run from the repo root: uv run python research/dip-timing/audit/<script>
import math
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

sys.path.insert(0, REPO + "/research/dip-timing")
import study as S  # noqa: E402

from lab.data.catalog import bar_type  # noqa: E402
from lab.data.external import HoldoutWindowError, holdout_cut, load_positioning  # noqa: E402
from lab.models import dips  # noqa: E402

CUT = holdout_cut()
TRAIN_CUT = S.TRAIN_LAST_CLOSE
print("cut", CUT, "train cut", TRAIN_CUT)
assert CUT == pd.Timestamp("2024-07-01", tz="UTC") and TRAIN_CUT == pd.Timestamp("2023-01-01", tz="UTC")

# ------------------------------------------------------------------ A. test-window guard on the real catalog
print("\n== A. guard")
from nautilus_trader.persistence import ParquetDataCatalog  # noqa: E402

cat = ParquetDataCatalog("data/catalog")
for inst in ("BTC/USD.KRAKEN", "ETH/USD.KRAKEN", "BTCUSDT.BINANCE", "ETHUSDT.BINANCE"):
    raw = cat.query_bars([bar_type(inst, "1d")], start=None, end=CUT.value)
    mx = pd.Timestamp(max(b.ts_init for b in raw), tz="UTC")
    for lc in (TRAIN_CUT, CUT):
        b = dips.load_study_bars(inst, lc)
        assert b.index.max() <= lc
        print(f"{inst:16s} last_close={lc.date()} rows={len(b)} first={b.index.min()} last={b.index.max()}")
    print(f"{inst:16s} raw nautilus query_bars(end=cut): {len(raw)} bars, max ts_init {mx} <= cut: {mx <= CUT}")
    for bad in (CUT + pd.Timedelta(microseconds=1), CUT + pd.Timedelta(days=1), pd.Timestamp("2026-01-01")):
        try:
            dips.load_study_bars(inst, bad)
            print("  NOT REFUSED", bad)
        except HoldoutWindowError:
            pass
print("requests after the cut refused for bars: ok")


def leaky(*a, **k):
    idx = pd.date_range("2024-06-29", periods=4, freq="D", tz="UTC")  # last one closes 2024-07-02 (test window)
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)


try:
    dips.load_study_bars("X", CUT, loader=leaky)
    print("leaky loader NOT caught")
except HoldoutWindowError as e:
    print("a loader that returns a test-window bar is caught:", e)
for sym in ("BTCUSDT", "ETHUSDT"):
    for bad in (CUT + pd.Timedelta(microseconds=1), CUT + pd.Timedelta(hours=1)):
        for fn in (lambda s=sym, b=bad: dips.load_study_positioning(s, b),
                   lambda s=sym, b=bad: load_positioning(s, "1d", end=b)):
            try:
                fn()
                print("positioning NOT refused", sym, bad)
            except HoldoutWindowError:
                pass
    for t in ("funding", "metrics"):
        k = pq.read_table(f"data/catalog/ext/binance_futures/{sym}/{t}.parquet", columns=["known_at"]).column(0)
        print(f"{sym} {t}: max known_at {k.to_pandas().max()} < cut: {k.to_pandas().max() < CUT}")
print("requests after the cut refused for positioning: ok")

# ------------------------------------------------------------------ train data (everything below: train only)
m = S.load_market("kraken", TRAIN_CUT)
for coin in S.COINS:
    assert m.bars[coin].index.max() <= TRAIN_CUT and m.pos[coin].index.max() <= TRAIN_CUT
ev = pd.read_parquet("results/dip-timing/train/events_d0.parquet")
assert ev["ts_end"].max() <= TRAIN_CUT

# ------------------------------------------------------------------ E. external alignment, recomputed from raw rows
print("\n== E. positioning recomputed from the raw stored rows (known_at < 2023-01-01 only)")
for coin in S.COINS:
    sym = S.PERP[coin]
    fund = pq.read_table(f"data/catalog/ext/binance_futures/{sym}/funding.parquet",
                         filters=[("known_at", "<", TRAIN_CUT)]).to_pandas()
    met = pq.read_table(f"data/catalog/ext/binance_futures/{sym}/metrics.parquet",
                        columns=["known_at", "open_interest"], filters=[("known_at", "<", TRAIN_CUT)]).to_pandas()
    fk = pd.DatetimeIndex(fund["known_at"]).as_unit("ns").asi8
    mk = pd.DatetimeIndex(met["known_at"]).as_unit("ns").asi8
    oi_vals = met["open_interest"].to_numpy(float)
    closes = m.bars[coin].index
    mine_f, mine_oi, max_used = [], [], []
    for t in closes:
        tn = t.value
        sel = (fk >= tn - 7 * 86400 * 10**9) & (fk < tn)
        mine_f.append(fund["rate"].to_numpy()[sel].mean() if sel.sum() == 21 else np.nan)
        if sel.any():
            max_used.append(fk[sel].max() - tn)
        ok = (mk < tn) & np.isfinite(oi_vals) & (oi_vals > 0)
        j = np.flatnonzero(ok)
        if len(j) and tn - mk[j[-1]] <= 3600 * 10**9:
            mine_oi.append(oi_vals[j[-1]])
            max_used.append(mk[j[-1]] - tn)
        else:
            mine_oi.append(np.nan)
    mine_f, mine_oi = np.array(mine_f), np.array(mine_oi)
    lab_f = m.pos[coin]["funding_mean_7d"].to_numpy(float)
    lab_oi = m.pos[coin]["oi_last"].to_numpy(float)
    same_f = np.array_equal(np.isnan(mine_f), np.isnan(lab_f)) and np.allclose(mine_f[~np.isnan(mine_f)],
                                                                                 lab_f[~np.isnan(lab_f)], rtol=0, atol=1e-15)
    same_oi = np.array_equal(np.isnan(mine_oi), np.isnan(lab_oi)) and np.array_equal(mine_oi[~np.isnan(mine_oi)],
                                                                                      lab_oi[~np.isnan(lab_oi)])
    print(f"{coin}: closes {len(closes)}; funding_7d defined {np.isfinite(mine_f).sum()} equal to lab: {same_f}; "
          f"oi_last defined {np.isfinite(mine_oi).sum()} equal to lab: {same_oi}; latest known_at used relative to "
          f"close: {pd.Timedelta(max(max_used))} (must be < 0)")
    # per event: funding_7d at t0 and oi_chg_dip by hand
    e = ev[ev.coin == coin]
    t0, ref = e["t0"].to_numpy(), e["ref_bar"].to_numpy()
    f_ok = np.allclose(np.nan_to_num(mine_f[t0], nan=-9), np.nan_to_num(e["funding_7d"].to_numpy(), nan=-9),
                       rtol=0, atol=1e-15)
    chg = np.log(mine_oi[t0] / mine_oi[ref])
    c_ok = np.allclose(np.nan_to_num(chg, nan=-9), np.nan_to_num(e["oi_chg_dip"].to_numpy(), nan=-9), rtol=1e-12)
    print(f"   events: funding_7d at t0 by hand equal: {f_ok}; oi_chg_dip by hand equal: {c_ok}; "
          f"covered funding {np.isfinite(e['funding_7d']).sum()}, oi {np.isfinite(e['oi_chg_dip']).sum()}")

# tamper the raw positioning rows known at/after a close, on 30 random real closes
from lab.data.external import positioning_at, read_table  # noqa: E402

rng = np.random.default_rng(2026)
for sym in ("BTCUSDT", "ETHUSDT"):
    f_all, m_all = read_table("data/catalog", sym, "funding"), read_table("data/catalog", sym, "metrics")
    f_tr = f_all[f_all["known_at"] < TRAIN_CUT].reset_index(drop=True)
    m_tr = m_all[m_all["known_at"] < TRAIN_CUT].reset_index(drop=True)
    del f_all, m_all
    closes = pd.date_range("2021-12-03", "2022-12-31", freq="D", tz="UTC")
    base = positioning_at(f_tr, m_tr, closes)
    bad = 0
    for t in rng.choice(closes, 30, replace=False):
        t = pd.Timestamp(t)
        f2, m2 = f_tr.copy(), m_tr.copy()
        f2.loc[f2["known_at"] >= t, "rate"] *= -7.0
        cols = [c for c in m2.columns if c not in ("ts", "known_at")]
        m2.loc[m2["known_at"] >= t, cols] = m2.loc[m2["known_at"] >= t, cols] * 3.0 + 1.0
        tam = positioning_at(f2, m2, closes)
        before = closes <= t
        a, b = base.loc[before].to_numpy(float), tam.loc[before].to_numpy(float)
        if not np.array_equal(np.isnan(a), np.isnan(b)) or not np.array_equal(a[~np.isnan(a)], b[~np.isnan(b)]):
            bad += 1
        after = closes > t + pd.Timedelta(days=1)
        moved = not np.allclose(np.nan_to_num(base.loc[after, "oi_last"].to_numpy(float)),
                                np.nan_to_num(tam.loc[after, "oi_last"].to_numpy(float)))
        assert moved, "the tamper must move later rows (sanity)"
    print(f"{sym}: tamper of every raw value known at or after 30 random closes: rows at or before the close "
          f"changed in {bad} of 30")

# ------------------------------------------------------------------ B. costs and fills by hand
print("\n== B. per-event returns by hand (own fill and cost code, costs parsed from config/costs.yaml)")
cy = yaml.safe_load(open("config/costs.yaml"))
TABLE = sorted((float(k), float(v)) for k, v in cy["slippage_bps"].items())


def slip(usd, mult):
    xs = [math.log10(a) for a, _ in TABLE]
    ys = [b for _, b in TABLE]
    if usd <= TABLE[0][0]:
        return ys[0] * mult
    lx = math.log10(usd)
    for i in range(1, len(xs)):
        if lx <= xs[i]:
            return mult * (ys[i - 1] + (ys[i] - ys[i - 1]) * (lx - xs[i - 1]) / (xs[i] - xs[i - 1]))
    return mult * (ys[-1] + (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) * (lx - xs[-1]))


def fee(trade_usd, port_usd, mult):  # fraction of the portfolio at the open
    w = trade_usd / port_usd
    return w * (mult * (cy["pool_fee_bps"] + cy["aggregator_fee_bps"]) + slip(trade_usd, mult)) / 1e4 + \
        mult * cy["gas_usd_per_trade"] / port_usd


def hand_event(b, t0, steps, mult=1.0, stop=0.15, hold=30):
    """steps: {offset: target weight}. Own mini-simulation: decide at close t0+k, fill at the open of the next
    bar; coin units held; stop at a close <= weighted average fill * (1 - stop); exit decided at close t0+hold."""
    o, c = b["open"].to_numpy(float), b["close"].to_numpy(float)
    cash, coins, ordered, paid, filled, pending = 10_000.0, 0.0, 0.0, 0.0, 0.0, None

    def exit_at(d1):
        port = cash + coins * o[d1]
        return port * (1 - fee(coins * o[d1], port, mult)) / 10_000 - 1

    for k in range(hold + 1):
        d = t0 + k
        if pending is not None:
            tgt, step = pending
            pending = None
            port = cash + coins * o[d]
            port *= 1 - fee(abs(tgt - coins * o[d] / port) * port, port, mult)
            coins = tgt * port / o[d]
            cash = port - coins * o[d]
            paid += o[d] * step
            filled += step
        if k == hold:
            return exit_at(d + 1) if filled > 0 else 0.0
        if filled > 0 and c[d] <= paid / filled * (1 - stop):
            return exit_at(d + 1)
        if k in steps and steps[k] > ordered:
            pending = (steps[k], steps[k] - ordered)
            ordered = steps[k]
    raise AssertionError


def first(sig, t0, k=10):
    hits = [o for o in range(k) if sig[t0 + o]]
    return hits[0] if hits else k - 1


res = {"T1": [], "T3": [], "T4": [], "T2": [], "T1x2": []}
for _, e in ev.iterrows():
    b = m.bars[e.coin]
    t0 = int(e.t0)
    up, narrow, close = dips.up_day(b), dips.narrow_range(b), b["close"].to_numpy(float)
    # own T3/T4 signals
    h, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    my_up = np.r_[False, close[1:] > h[:-1]]
    lr = np.log(h / lo)
    my_nr = np.array([False] * 5 + [lr[t] < lr[t - 5:t].mean() for t in range(5, len(lr))])
    assert np.array_equal(my_up, up) and np.array_equal(my_nr, narrow)
    res["T1"].append(hand_event(b, t0, {0: 1.0}))
    res["T1x2"].append(hand_event(b, t0, {0: 1.0}, mult=2.0))
    res["T3"].append(hand_event(b, t0, {first(my_up, t0): 1.0}))
    res["T4"].append(hand_event(b, t0, {first(my_nr, t0): 1.0}))
    lv = [e.p_ref * (1 - 0.15 - s) for s in (0.05, 0.10)]
    steps, w, lowc = {}, 0.0, math.inf
    for o_ in range(10):
        lowc = min(lowc, close[t0 + o_])
        ww = (1 + sum(lowc <= x for x in lv)) / 3
        if ww > w:
            steps[o_], w = ww, ww
    res["T2"].append(hand_event(b, t0, steps))
for rule, col in (("T1", "r_V01"), ("T2", "r_V02"), ("T3", "r_V03"), ("T4", "r_V04")):
    d = np.abs(np.array(res[rule]) - ev[col].to_numpy())
    print(f"{rule}: 80 events, max |hand - study| = {d.max():.3e}; hand mean r_e {np.mean(res[rule]):+.4%}")
print(f"T1 at 2x costs by hand: mean r_e {np.mean(res['T1x2']):+.4%} (RESULTS: V36 +3.33%)")
r1 = np.array(res["T1"])
print(f"T1 by hand: median {np.median(r1):+.4%}, winners {np.mean(r1 > 0):.4f}, y_Q share BTC "
      f"{np.mean(r1[ev.coin == 'BTC'] > 0):.4f} ETH {np.mean(r1[ev.coin == 'ETH'] > 0):.4f}; "
      f"median BTC {np.median(r1[ev.coin == 'BTC']):+.4%} ETH {np.median(r1[ev.coin == 'ETH']):+.4%}")
cost_rt = fee(10_000, 10_000, 1.0) * 2
print(f"round-trip cost at USD 10,000 (both legs, approx): {cost_rt:.4%}")

# ------------------------------------------------------------------ C. strategy level T1, own simulation
print("\n== C. strategy level T1 (both sleeves) by hand")
vals = {}
for coin in S.COINS:
    b = m.bars[coin].loc[S.in_window(m.bars[coin].index, S.TRAIN)]
    o, c = b["open"].to_numpy(float), b["close"].to_numpy(float)
    full = m.bars[coin]
    off = int(np.flatnonzero(full.index == b.index[0])[0])
    v = np.full(len(b), np.nan)
    cash, coins = 10_000.0, 0.0
    evc = ev[ev.coin == coin]
    plan = {}
    for _, e in evc.iterrows():  # T1 with the 15% stop: entry at t0+1, exit at the stop or t0+31
        t0 = int(e.t0) - off
        entry = t0 + 1
        ex = t0 + 31
        for d in range(entry, t0 + 30):
            if c[d] <= o[entry] * 0.85:
                ex = d + 1
                break
        plan[entry], plan[ex] = "buy", "sell"
    for t in range(len(b)):
        if plan.get(t) == "buy":
            port = cash
            kf = fee(port, port, 1.0)
            coins, cash = port * (1 - kf) / o[t], 0.0
        elif plan.get(t) == "sell":
            port = coins * o[t]
            kf = fee(port, port, 1.0)
            cash, coins = port * (1 - kf), 0.0
        v[t] = cash + coins * c[t]
    vals[coin] = pd.Series(v, index=b.index)
tot = pd.DataFrame(vals).sort_index().ffill().fillna(10_000.0).sum(axis=1)
ret = (tot / tot.shift(1) - 1).fillna(0.0).to_numpy().copy()
ret[0] = tot.iloc[0] / 20_000 - 1
sh = ret.mean() / ret.std(ddof=1) * math.sqrt(365)
eq = np.cumprod(1 + ret)
mdd = (eq / np.maximum.accumulate(eq) - 1).min()
ser = pd.read_parquet("results/dip-timing/train/series.parquet")["V01_path0"].to_numpy()
print(f"hand: Sharpe {sh:.4f}, total {eq[-1] - 1:+.4%}, max DD {mdd:.4%}; max |hand - logged daily ret| "
      f"{np.abs(ret - ser).max():.2e}")
print("average daily simple return (train closes, close-to-close):",
      {coin: f"{m.bars[coin]['close'].pct_change().loc[S.in_window(m.bars[coin].index, S.TRAIN)].mean():+.4%}"
       for coin in S.COINS})
