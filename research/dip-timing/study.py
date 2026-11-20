"""Dip-timing study pipeline ("option C"), run exactly as pre-registered in research/dip-timing/PLAN.md.

SCOUTING ONLY. Every profit number here comes from the reference backtester (lab.runner.reference), not from
NautilusTrader (AGENTS.md hard rule 3; the Nautilus runner is on hold). Nothing from this study goes into
reports/<strategy>/.

The computations live in tested code (lab/models/dips.py, lab/runner/reference.py, lab/validation/); this file
only orchestrates them. research/ is never imported by lab/.

The test window is never read: every bar and positioning load goes through dips.load_study_bars /
dips.load_study_positioning, which refuse anything closing after 2024-07-01 00:00 UTC, and load_market checks
again (check_before_holdout) on what it got.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import in_window, splits
from lab.data.external import holdout_cut
from lab.models import dips
from lab.models.features import FEATURES, compute_features
from lab.models.train import class_metrics
from lab.runner import reference
from lab.runner.reference import Costs
from lab.validation import montecarlo, stats

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LABEL = "SCOUTING: reference backtester, not NautilusTrader (AGENTS.md hard rule 3)"

SPLITS = splits()
TRAIN, VALIDATE = SPLITS["train"], SPLITS["validate"]
TRAIN_LAST_CLOSE = TRAIN[1] + pd.Timedelta(days=1)  # 2023-01-01 00:00 UTC
VALIDATE_LAST_CLOSE = holdout_cut()  # 2024-07-01 00:00 UTC
assert VALIDATE_LAST_CLOSE == pd.Timestamp("2024-07-01", tz="UTC")

COINS = ("BTC", "ETH")
KRAKEN = {"BTC": "BTC/USD.KRAKEN", "ETH": "ETH/USD.KRAKEN"}
BINANCE = {"BTC": "BTCUSDT.BINANCE", "ETH": "ETHUSDT.BINANCE"}
PERP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
CELLS = tuple((x, n) for x in (0.10, 0.15, 0.20) for n in (10, 20, 30))
D0 = dips.DipSpec()
N_GROUPS, N_TEST_GROUPS, N_PATHS = 6, 2, 5
N_NULL, N_BOOT, SEED = 100, 10_000, 0
PBO_BLOCKS = 10
THETA_SHIFT = 0.10
POWER_Z = 2.5
CAPITAL = 10_000.0
T1_PLAN = ((0, 1.0),)

Q_COLS = list(dips.Q_FEATURES)
B_LOGIT_COLS = list(dips.B_FEATURES)
B_GBM_COLS = list(dips.B_FEATURES) + list(dips.Q_FEATURES) + list(FEATURES)

# Choices the plan leaves open, fixed here BEFORE any real-data run (they are part of the frozen config).
INTERPRETATIONS = {
    "event_dedup": "De-duplication runs over every trigger from the first loaded bar (2017-01-02 close); events "
    "before bar 100 or whose span leaves the window are dropped but still block their 31-bar cool-off. This "
    "reading reproduces every count of the PLAN.md section 2 table on the train window.",
    "r_e": "Per-event net return on a fresh USD 10,000 sleeve (cash before entry and after exit), through "
    "reference.scheduled on bars t0..t0+H+1, after all costs of every fill. The strategy level compounds one "
    "sleeve per coin over the whole window instead.",
    "average_fill_price": "Mean of the fill opens weighted by each tranche's target-weight step (T2: 1/3 each).",
    "stop_order": "At a close where both a stop and a T2 tranche trigger, the stop wins and the event is over.",
    "forced_entry": "T3-T5 that never fire buy at the open after t0+9 (decision at close t0+9); a signal on "
    "t0+9 itself is not counted as forced.",
    "t5_threshold": "theta_B = share of y_B = 1 in the split's training day rows; fires at p >= theta_B - 1e-9.",
    "q_threshold": "theta_Q = share of y_Q = 1 in the split's training events; take at p >= theta_Q - 1e-9.",
    "lightgbm_features": "B_FEATURES at d, the 3 Q features at t0 (event constants) and the 15 lab features at d.",
    "b_depth": "ln(close[d] / P_ref) / (ewma_vol_20[d] * sqrt(20)); b_bounce = ln(close[d] / min(low[t0..d])).",
    "funding_7d": "external.funding_mean_7d at the close (mean of the funding rates known strictly before it over "
    "7 days; checked to be exactly 21 eight-hour prints wherever it is defined).",
    "oi_snapshot": "external.oi_last: the newest 5-minute open interest with known_at = create_time + 5 min "
    "strictly before the close. This is 5 minutes earlier than PLAN.md's 'at or before close - 5 min' (see "
    "Deviations: the data-engineer found create_time is the START of the period in files from 2024-04-26).",
    "coverage": "funding-covered = funding_7d finite at t0 and on every entry day; OI-covered = funding-covered "
    "and oi_chg_dip finite (V15/V16 use funding + OI).",
    "positioning_cpcv": "V11-V16 run their own 6-group CPCV over the covered events only (pairs share it).",
    "v13_v14_model": "T5 with the logistic B model (V05's), because LightGBM's min_child_samples=200 cannot split "
    "on the ~250 training day rows of the covered subset.",
    "criterion_1_model_delta": "For model variants, an event's delta is the mean of its 5 path deltas.",
    "bootstrap": "Shifted (null-centred) block bootstrap over trigger months: p = (1 + #{mean* - mean >= mean}) / "
    "(B + 1); trigger month = calendar month of the trigger day (bar closing at ts0 covers ts0 - 1 day).",
    "null_combination": "V09-V10 must beat the 95th percentile of BOTH the random-timing and the random-skip "
    "nulls (the combined null is reported too).",
    "null_skip_count": "Random skipping drops round(mean number of skipped events over the 5 paths) events.",
    "best": "Best = highest train mean r_e among V01-V10 passing criteria 1-3 (criterion 2 only for model "
    "variants), else the highest among V01-V10.",
    "theta_fallback": "If the best variant has no model threshold, V33-V34 shift the thresholds of the model "
    "variant among V05-V10 with the highest train mean r_e. Both theta_Q and theta_B shift when both exist.",
    "sensitivity_reference": "V25-V32 are compared with V17-V24 (T1, same cell), V35 with V36, V37 with V38; "
    "V39 and V40 with T1 on the same definition (reference computations, not trials).",
    "binance_events": "V37-V38 find events on the Binance bars themselves (bar 100 of that series onward).",
    "embargo": "Embargo = H + 1 calendar days after a test group's span (31 days for H = 30, 21 for H = 20).",
    "validate": "One look: models refit on all train events (or the covered subset), applied to validate events; "
    "V01-V16, the baselines and the nulls reported; nothing is tuned or rerun after it.",
}


# --------------------------------------------------------------------------------------------- the data


@dataclass
class Market:
    source: str
    bars: dict[str, pd.DataFrame]
    feats: dict[str, pd.DataFrame]
    funding: dict[str, np.ndarray]
    pos: dict[str, pd.DataFrame]
    snapshot: str
    last_close: pd.Timestamp


def load_market(source: str, last_close: pd.Timestamp, catalog_dir: str = "data/catalog") -> Market:
    """Bars (Kraken or Binance) and positioning for both coins, up to ``last_close`` (<= the validate cut)."""
    instruments = {"kraken": KRAKEN, "binance": BINANCE}[source]
    bars, feats, funding, pos = {}, {}, {}, {}
    snapshot = None
    for coin in COINS:
        b = dips.load_study_bars(instruments[coin], last_close, catalog_dir=catalog_dir)
        dips.check_before_holdout(b.index)
        assert b.index.max() <= last_close <= VALIDATE_LAST_CLOSE
        p = dips.load_study_positioning(PERP[coin], last_close, catalog_dir=catalog_dir)
        dips.check_before_holdout(p.index)
        p = p.reindex(b.index)
        defined = p["funding_mean_7d"].notna().to_numpy()
        assert (p["funding_count_7d"].to_numpy()[defined] == 21).all(), "funding_7d must be 21 prints"
        bars[coin], feats[coin], pos[coin] = b, compute_features(b), p
        funding[coin] = p["funding_mean_7d"].to_numpy(dtype=float)
        sid = b.attrs.get("snapshot_id")
        assert snapshot in (None, sid) and p.attrs.get("snapshot_id") in (None, sid)
        snapshot = sid
    return Market(source, bars, feats, funding, pos, snapshot, last_close)


def synthetic_market_for_dry_run(seed: int = 7, last_close: pd.Timestamp = TRAIN_LAST_CLOSE) -> Market:
    """Synthetic bars and fake positioning, 2017-01-02 .. 2024-07-01 cut at ``last_close``, ONLY to dry-run the
    pipeline (no real data is read)."""
    from lab.data.synthetic import synthetic_market

    raw = synthetic_market(2738, seed=seed, start="2017-01-02")
    bars, feats, funding, pos = {}, {}, {}, {}
    rng = np.random.default_rng(seed)
    for coin in COINS:
        full = raw[coin]
        n = len(full)
        f = np.full(n, np.nan)
        start_f = int(np.searchsorted(full.index, pd.Timestamp("2020-01-08", tz="UTC")))
        f[start_f:] = 1e-4 + np.cumsum(rng.normal(0, 2e-5, n - start_f)) * 0.1
        oi = np.full(n, np.nan)
        oi_start = "2020-09-01" if coin == "BTC" else "2021-12-01"
        start_o = int(np.searchsorted(full.index, pd.Timestamp(oi_start, tz="UTC")))
        oi[start_o:] = 1e5 * np.exp(np.cumsum(rng.normal(0, 0.03, n - start_o)))
        p = pd.DataFrame({"funding_mean_7d": f, "funding_count_7d": np.where(np.isnan(f), 0, 21), "oi_last": oi},
                         index=full.index)
        keep = full.index <= last_close
        b = full.loc[keep]
        bars[coin], feats[coin], pos[coin] = b, compute_features(b), p.loc[keep]
        funding[coin] = p.loc[keep, "funding_mean_7d"].to_numpy()
    return Market("synthetic", bars, feats, funding, pos, "synthetic", last_close)


@dataclass
class EventSet:
    name: str
    market: Market
    spec: dips.DipSpec
    costs: Costs
    window: tuple
    events: pd.DataFrame
    days: pd.DataFrame
    signals: dict
    cache: dict = field(default_factory=dict)


def build_eventset(name: str, market: Market, spec: dips.DipSpec, costs: Costs, window: tuple) -> EventSet:
    """Events of both coins in ``window`` (whole span inside), pooled and sorted by (ts0, coin), with their
    features, positioning, labels and day rows."""
    ev_parts, day_parts, signals = [], [], {}
    for coin in COINS:
        b, f = market.bars[coin], market.feats[coin]
        ev = dips.find_events(b, spec)
        ev = ev.loc[dips.window_events(ev, window)].copy()
        ev = ev.join(dips.event_features(b, ev, spec, f))
        _, oi_chg = dips.positioning_features(b, ev, market.pos[coin])
        t0 = ev["t0"].to_numpy(dtype=np.int64)
        ev["coin"] = coin
        ev["local"] = ev.index
        ev["funding_7d"] = market.funding[coin][t0]
        ev["oi_chg_dip"] = oi_chg
        rows = dips.day_rows(b, ev, spec, f)
        rows["coin"] = coin
        rows["funding_7d"] = market.funding[coin][rows["d"].to_numpy(dtype=np.int64)]
        rows["y_B"] = dips.bottom_label(b, rows["d"].to_numpy(dtype=np.int64), spec)
        ev_parts.append(ev)
        day_parts.append(rows)
        signals[coin] = (dips.up_day(b), dips.narrow_range(b), b["close"].to_numpy(dtype=float))
    events = pd.concat(ev_parts, ignore_index=True)
    events = events.sort_values(["ts0", "coin"], kind="stable").reset_index(drop=True)
    key = {(c, int(lo)): i for i, (c, lo) in enumerate(zip(events["coin"], events["local"], strict=True))}
    days = pd.concat(day_parts, ignore_index=True)
    days["event"] = [key[(c, int(e))] for c, e in zip(days["coin"], days["event"], strict=True)]
    days = days.sort_values(["event", "offset"], kind="stable").reset_index(drop=True)
    assert days["y_B"].notna().all(), "every y_B window lies inside its event span"
    events["month"] = dips.trigger_months(events)
    es = EventSet(name, market, spec, costs, window, events, days, signals)
    events["r_T1"] = [outcome(es, e, T1_PLAN)["r"] for e in range(len(events))]
    events["y_Q"] = (events["r_T1"] > 0).astype(float)
    day_funding_ok = days.groupby("event")["funding_7d"].apply(lambda s: bool(np.isfinite(s).all()))
    events["funding_covered"] = np.isfinite(events["funding_7d"]) & day_funding_ok.reindex(events.index).to_numpy()
    assert (events["funding_covered"] == np.isfinite(events["funding_7d"])).all()
    events["oi_covered"] = events["funding_covered"] & np.isfinite(events["oi_chg_dip"])
    return es


def outcome(es: EventSet, e: int, plan) -> dict:
    """``dips.run_event`` for pooled event ``e`` and ``plan`` (cached)."""
    key = (e, tuple(plan))
    if key not in es.cache:
        coin = es.events.at[e, "coin"]
        es.cache[key] = dips.run_event(es.market.bars[coin], int(es.events.at[e, "t0"]), plan, es.spec, es.costs)
    return es.cache[key]


def rule_plan(es: EventSet, e: int, rule: str):
    """(plan, forced) of a fixed rule T1-T4 for pooled event ``e``."""
    if rule == "T1":
        return T1_PLAN, False
    coin = es.events.at[e, "coin"]
    t0, k = int(es.events.at[e, "t0"]), es.spec.entry_window
    up, narrow, close = es.signals[coin]
    if rule == "T2":
        return dips.ladder_plan(close, t0, float(es.events.at[e, "p_ref"]), es.spec), False
    if rule == "T3":
        return dips.first_signal_plan(up[t0 : t0 + k])
    if rule == "T4":
        return dips.first_signal_plan(narrow[t0 : t0 + k])
    raise ValueError(rule)


# ------------------------------------------------------------------------------------------- variants


@dataclass(frozen=True)
class Recipe:
    timing: str  # T1 .. T5
    filter: str | None = None  # None, "vol", "Q"
    q_extra: tuple[str, ...] = ()
    b_model: str = "logistic"
    b_extra: tuple[str, ...] = ()
    subset: str | None = None  # None, "funding", "oi"
    theta_shift: float = 0.0

    @property
    def fitted(self) -> bool:
        return self.filter is not None or self.timing == "T5"

    def describe(self) -> dict:
        model = []
        if self.filter == "Q":
            model.append(f"Q: logistic C=1 on {Q_COLS + list(self.q_extra)}")
        elif self.filter == "vol":
            model.append("vol-only: logistic C=1 on ['ewma_vol_20']")
        if self.timing == "T5":
            cols = (B_LOGIT_COLS if self.b_model == "logistic" else B_GBM_COLS) + list(self.b_extra)
            model.append(f"B: {self.b_model} on {len(cols)} features {cols if len(cols) < 10 else ''}".strip())
        return {"rule": self.timing, "filter": self.filter, "model": "; ".join(model) or "none",
                "subset": self.subset or "all", "theta_shift": self.theta_shift}


def q_cols(recipe: Recipe) -> list[str]:
    return (["ewma_vol_20"] if recipe.filter == "vol" else list(Q_COLS)) + list(recipe.q_extra)


def b_cols(recipe: Recipe) -> list[str]:
    return (list(B_LOGIT_COLS) if recipe.b_model == "logistic" else list(B_GBM_COLS)) + list(recipe.b_extra)


def subset_of(es: EventSet, recipe: Recipe) -> np.ndarray:
    if recipe.subset is None:
        return np.arange(len(es.events))
    col = {"funding": "funding_covered", "oi": "oi_covered"}[recipe.subset]
    return np.flatnonzero(es.events[col].to_numpy(dtype=bool))


def fit_models(es: EventSet, recipe: Recipe, train_ev: np.ndarray, y_q: np.ndarray | None = None,
               y_b: np.ndarray | None = None) -> dict:
    """Fit the recipe's models on the training events ``train_ev`` of ``es`` only. ``y_q`` / ``y_b`` replace the
    event / day labels (used by the run-time leak check). Returns ``{"q": (clf, theta), "b": (clf, theta)}``."""
    ev, days = es.events, es.days
    models: dict = {}
    if recipe.filter is not None:
        cols = q_cols(recipe)
        y = ev["y_Q"].to_numpy() if y_q is None else y_q
        clf = dips.DipClassifier("logistic", SEED).fit(ev.loc[train_ev, cols], y[train_ev])
        models["q"] = (clf, float(y[train_ev].mean()) + recipe.theta_shift)
    if recipe.timing == "T5":
        cols = b_cols(recipe)
        rows = days["event"].isin(train_ev).to_numpy()
        y = days["y_B"].to_numpy() if y_b is None else y_b
        clf = dips.DipClassifier(recipe.b_model, SEED).fit(days.loc[rows, cols], y[rows])
        models["b"] = (clf, float(y[rows].mean()) + recipe.theta_shift)
    return models


def decide(es: EventSet, recipe: Recipe, models: dict, test_ev: np.ndarray) -> dict:
    """Apply fitted models to the events ``test_ev`` of ``es`` (which may be another window's event set):
    ``take`` (filter), ``offset`` and ``forced`` (T5), the probabilities and the test AUCs."""
    ev, days = es.events, es.days
    out: dict = {}
    if "q" in models:
        clf, theta = models["q"]
        p = clf.predict(ev.loc[test_ev, q_cols(recipe)])
        out.update(take=dips.fires(p, theta), p_q=p, theta_q=theta,
                   q_auc=class_metrics(ev.loc[test_ev, "y_Q"].to_numpy(), p)["auc"])
    if "b" in models:
        clf, theta_b = models["b"]
        te = days.loc[days["event"].isin(test_ev)]
        p = clf.predict(te[b_cols(recipe)])
        offsets, forced = [], []
        k = es.spec.entry_window
        for e in test_ev:
            rows = (te["event"] == e).to_numpy()
            assert rows.sum() == k
            plan, f = dips.first_signal_plan(dips.fires(p[rows], theta_b))
            offsets.append(plan[0][0])
            forced.append(f)
        out.update(offset=np.array(offsets, dtype=float), forced=np.array(forced, dtype=float), theta_b=theta_b,
                   p_b=p, b_auc=class_metrics(te["y_B"].to_numpy(), p)["auc"])
    return out


def fit_and_decide(es: EventSet, recipe: Recipe, train_ev: np.ndarray, test_ev: np.ndarray) -> dict:
    """Fit on ``train_ev`` and decide for ``test_ev``. Checks at run time that the decisions and probabilities
    don't change when every label outside the training events is flipped (the fit can only see training rows)."""
    out = decide(es, recipe, fit_models(es, recipe, train_ev), test_ev)
    y_q = 1.0 - es.events["y_Q"].to_numpy()
    y_q[train_ev] = es.events["y_Q"].to_numpy()[train_ev]
    y_b = 1.0 - es.days["y_B"].to_numpy()
    in_train = es.days["event"].isin(train_ev).to_numpy()
    y_b[in_train] = es.days["y_B"].to_numpy()[in_train]
    again = decide(es, recipe, fit_models(es, recipe, train_ev, y_q, y_b), test_ev)
    for key in ("p_q", "p_b"):
        if key in out:
            assert np.array_equal(out[key], again[key]), f"{key}: the fit saw a label outside its training events"
    return out


@dataclass
class VariantResult:
    vid: str
    recipe: Recipe
    es: EventSet
    events: np.ndarray  # pooled event indices
    plans: list  # [path][i] plan
    forced: np.ndarray  # (paths, n)
    r: np.ndarray  # (paths, n)
    r_t1: np.ndarray  # (n,)
    info: dict  # per-path arrays: entered, partial, stopped, distance, mae
    auc: dict  # per-split lists
    splits_meta: list = field(default_factory=list)
    strategy: list = field(default_factory=list)  # per path dict
    series: list = field(default_factory=list)  # per path pd.Series (combined daily returns)

    @property
    def delta(self) -> np.ndarray:
        return self.r - self.r_t1[None, :]


def evaluate(vid: str, es: EventSet, recipe: Recipe) -> VariantResult:
    """Event-level CPCV evaluation of one variant (5 paths; a fixed rule gives the same plan on every path)."""
    sub = subset_of(es, recipe)
    n = len(sub)
    auc: dict = {"q": [], "b": []}
    meta = []
    if not recipe.fitted:
        base = [rule_plan(es, int(e), recipe.timing) for e in sub]
        plans = [[p for p, _ in base] for _ in range(N_PATHS)]
        forced = np.tile(np.array([f for _, f in base], dtype=float), (N_PATHS, 1))
    else:
        ts0 = es.events.loc[sub, "ts0"]
        ts_end = es.events.loc[sub, "ts_end"]
        splits_ = dips.event_cpcv(ts0, ts_end, N_GROUPS, N_TEST_GROUPS, pd.Timedelta(days=es.spec.hold + 1))
        vals: dict[str, list] = {"take": [], "offset": [], "forced": []}
        for train_pos, test_pos, groups in splits_:
            # purge property, checked at run time on the real spans as well (tested in tests/test_dips.py)
            emb = pd.Timedelta(days=es.spec.hold + 1)
            for g in groups:
                gi = np.array_split(np.arange(n), N_GROUPS)[g]
                lo, hi = ts0.iloc[gi].min(), ts_end.iloc[gi].max()
                tr0, tr1 = ts0.iloc[train_pos], ts_end.iloc[train_pos]
                assert ((tr1 < lo) | (tr0 > hi + emb)).all()
            d = fit_and_decide(es, recipe, sub[train_pos], sub[test_pos])
            meta.append({"groups": list(groups), "n_train": len(train_pos), "n_test": len(test_pos),
                         "theta_q": d.get("theta_q"), "theta_b": d.get("theta_b")})
            vals["take"].append(d["take"].astype(float) if "take" in d else np.ones(len(test_pos)))
            vals["offset"].append(d["offset"] if "offset" in d else np.zeros(len(test_pos)))
            vals["forced"].append(d["forced"] if "forced" in d else np.zeros(len(test_pos)))
            if "q_auc" in d:
                auc["q"].append(d["q_auc"])
            if "b_auc" in d:
                auc["b"].append(d["b_auc"])
        paths = {k: dips.event_paths(n, N_GROUPS, N_TEST_GROUPS, v) for k, v in vals.items()}
        plans, forced = [], np.zeros((N_PATHS, n))
        for j in range(N_PATHS):
            row = []
            for i, e in enumerate(sub):
                if recipe.timing == "T5":
                    plan, f = ((int(paths["offset"][j, i]), 1.0),), bool(paths["forced"][j, i])
                else:
                    plan, f = rule_plan(es, int(e), recipe.timing)
                if paths["take"][j, i] < 0.5:
                    plan, f = (), False
                row.append(plan)
                forced[j, i] = float(f)
            plans.append(row)
    r = np.zeros((N_PATHS, n))
    info = {k: np.full((N_PATHS, n), np.nan) for k in ("entered", "partial", "stopped", "distance", "mae")}
    for j in range(N_PATHS):
        for i, e in enumerate(sub):
            o = outcome(es, int(e), plans[j][i])
            r[j, i] = o["r"]
            info["entered"][j, i] = float(o["entered"])
            info["partial"][j, i] = float(o["entered"] and o["final_weight"] < 1.0)
            info["stopped"][j, i] = float(o["stop_bar"] is not None)
            info["distance"][j, i] = o["distance"]
            info["mae"][j, i] = o["mae"]
    r_t1 = es.events.loc[sub, "r_T1"].to_numpy()
    return VariantResult(vid, recipe, es, sub, plans, forced, r, r_t1, info, auc, meta)


def evaluate_holdout(vid: str, es_train: EventSet, es_test: EventSet, recipe: Recipe) -> VariantResult:
    """The validate look: fit once on every training event of ``es_train`` (the recipe's subset), apply to the
    events of ``es_test`` (same subset rule). One path."""
    tr, te = subset_of(es_train, recipe), subset_of(es_test, recipe)
    auc: dict = {"q": [], "b": []}
    plans, forced = [[]], np.zeros((1, len(te)))
    meta = []
    if recipe.fitted:
        models = fit_models(es_train, recipe, tr)
        d = decide(es_test, recipe, models, te)
        meta.append({"n_train": len(tr), "n_test": len(te), "theta_q": d.get("theta_q"), "theta_b": d.get("theta_b"),
                     "p_q": d.get("p_q"), "take": d.get("take")})
        if "q_auc" in d:
            auc["q"].append(d["q_auc"])
        if "b_auc" in d:
            auc["b"].append(d["b_auc"])
    for i, e in enumerate(te):
        if recipe.timing == "T5":
            plan, f = ((int(d["offset"][i]), 1.0),), bool(d["forced"][i])
        else:
            plan, f = rule_plan(es_test, int(e), recipe.timing)
        if recipe.filter is not None and not d["take"][i]:
            plan, f = (), False
        plans[0].append(plan)
        forced[0, i] = float(f)
    r = np.zeros((1, len(te)))
    info = {k: np.full((1, len(te)), np.nan) for k in ("entered", "partial", "stopped", "distance", "mae")}
    for i, e in enumerate(te):
        o = outcome(es_test, int(e), plans[0][i])
        r[0, i] = o["r"]
        info["entered"][0, i] = float(o["entered"])
        info["partial"][0, i] = float(o["entered"] and o["final_weight"] < 1.0)
        info["stopped"][0, i] = float(o["stop_bar"] is not None)
        info["distance"][0, i] = o["distance"]
        info["mae"][0, i] = o["mae"]
    r_t1 = es_test.events.loc[te, "r_T1"].to_numpy()
    return VariantResult(vid, recipe, es_test, te, plans, forced, r, r_t1, info, auc, meta)


# -------------------------------------------------------------------------------------- strategy level


def _sleeve_values(es: EventSet, coin: str, plan_by_event: dict, costs: Costs | None = None) -> tuple:
    b = es.market.bars[coin]
    mask = in_window(b.index, es.window)
    targets = {e: dips.event_targets(b, int(es.events.at[e, "t0"]), plan, es.spec)[0]
               for e, plan in plan_by_event.items() if plan}
    col = dips.schedule_column(len(b), es.events, targets)
    piece = b.loc[mask, ["open", "high", "low", "close", "volume"]]
    res = reference.scheduled({"col": "target"}, piece.assign(target=col[mask]), costs or es.costs)
    v = CAPITAL * np.cumprod(1.0 + res["ret"].to_numpy())
    return pd.Series(v, index=piece.index), int(res.attrs["n_trades"]), float(res["turnover"].sum())


def combine(values: dict[str, pd.Series]) -> pd.Series:
    """Daily return of both sleeves together (sum of the two USD values; a coin without a bar keeps its value)."""
    frame = pd.DataFrame(values).sort_index().ffill().fillna(CAPITAL)
    total = frame.sum(axis=1)
    ret = total / total.shift(1) - 1.0
    ret.iloc[0] = total.iloc[0] / (CAPITAL * len(values)) - 1.0
    return ret


def strategy_stats(ret: pd.Series, n_trades: int, turnover: float) -> dict:
    r = ret.to_numpy(dtype=float)
    return {
        "sharpe": stats.annualized_sharpe(r),
        "total_return": float(np.prod(1.0 + r) - 1.0),
        "max_drawdown": montecarlo.max_drawdown(r),
        "n_trades": n_trades,
        "turnover": turnover,
    }


def run_strategy(vr: VariantResult) -> None:
    """Both sleeves through the reference engine per path (SCOUTING), compounding over the window."""
    es = vr.es
    cache: dict = {}
    for j in range(len(vr.plans)):
        values, trades, turnover = {}, 0, 0.0
        for coin in COINS:
            plan_by_event = {int(e): vr.plans[j][i] for i, e in enumerate(vr.events)
                             if es.events.at[int(e), "coin"] == coin}
            key = (coin, tuple(sorted(plan_by_event.items())))
            if key not in cache:
                cache[key] = _sleeve_values(es, coin, plan_by_event)
            v, nt, to = cache[key]
            values[coin], trades, turnover = v, trades + nt, turnover + to
        ret = combine(values)
        vr.series.append(ret)
        vr.strategy.append(strategy_stats(ret, trades, turnover))


def benchmarks(es: EventSet, n_t1_trips: dict[str, int]) -> dict:
    """Buy-and-hold, 50/50 monthly, and the random-entry null (100 seeds) over the window (SCOUTING)."""
    out = {}
    for name, fn, params in (("buy_and_hold", reference.buy_and_hold, {}),
                             ("mix_50_50_every_30", reference.constant_mix, {"weight": 0.5, "every": 30})):
        values, trades, turnover = {}, 0, 0.0
        for coin in COINS:
            b = es.market.bars[coin]
            piece = b.loc[in_window(b.index, es.window), ["open", "high", "low", "close", "volume"]]
            res = fn(params, piece, es.costs)
            values[coin] = pd.Series(CAPITAL * np.cumprod(1.0 + res["ret"].to_numpy()), index=piece.index)
            trades += int(res.attrs["n_trades"])
            turnover += float(res["turnover"].sum())
        ret = combine(values)
        out[name] = {**strategy_stats(ret, trades, turnover), "series": ret}
    sharpes, totals = [], []
    for seed in range(N_NULL):
        values = {}
        for coin in COINS:
            b = es.market.bars[coin]
            piece = b.loc[in_window(b.index, es.window), ["open", "high", "low", "close", "volume"]]
            res = reference.random_entry({"n_trades": n_t1_trips[coin], "hold": es.spec.hold, "seed": seed},
                                         piece, es.costs)
            values[coin] = pd.Series(CAPITAL * np.cumprod(1.0 + res["ret"].to_numpy()), index=piece.index)
        ret = combine(values)
        sharpes.append(stats.annualized_sharpe(ret.to_numpy()))
        totals.append(float(np.prod(1.0 + ret.to_numpy()) - 1.0))
    out["random_entry"] = {"sharpe": sharpes, "total_return": totals}
    return out


# ----------------------------------------------------------------------------------------------- nulls


def single_entry_table(es: EventSet) -> np.ndarray:
    """R[e, o]: net event return of a full entry decided at offset o (o = 0..K-1), every event."""
    k = es.spec.entry_window
    return np.array([[outcome(es, e, ((o, 1.0),))["r"] for o in range(k)] for e in range(len(es.events))])


def null_means(table: np.ndarray, kind: str, n_skip: int = 0) -> np.ndarray:
    """Mean r_e of N_NULL seeded draws: ``timing`` (random entry day), ``skip`` (skip n_skip random events, T1
    on the rest) or ``both``. Seed s uses np.random.default_rng(s)."""
    n, k = table.shape
    out = np.empty(N_NULL)
    for s in range(N_NULL):
        rng = np.random.default_rng(s)
        skip = np.zeros(n, dtype=bool)
        if kind in ("skip", "both"):
            skip[rng.choice(n, size=n_skip, replace=False)] = True
        offsets = rng.integers(0, k, size=n) if kind in ("timing", "both") else np.zeros(n, dtype=int)
        out[s] = np.where(skip, 0.0, table[np.arange(n), offsets]).mean()
    return out


# ------------------------------------------------------------------------------------------- summaries


def summarize(vr: VariantResult) -> dict:
    es = vr.es
    months = es.events.loc[vr.events, "month"].to_numpy()
    d_event = vr.delta.mean(axis=0)  # an event's delta averaged over the paths
    r_event = vr.r.mean(axis=0)
    boot = dips.month_bootstrap(d_event, months, N_BOOT, SEED) if len(d_event) else {}
    entered = vr.info["entered"]
    dist = vr.info["distance"][entered == 1.0]
    mae = vr.info["mae"][entered == 1.0]
    path_delta = vr.delta.mean(axis=1)
    out = {
        "vid": vr.vid,
        "eventset": es.name,
        "n_events": int(len(vr.events)),
        "n_btc": int((es.events.loc[vr.events, "coin"] == "BTC").sum()),
        "mean_r": float(r_event.mean()),
        "median_r": float(np.median(r_event)),
        "mean_r_t1": float(vr.r_t1.mean()),
        "mean_delta": float(d_event.mean()),
        "sd_delta": float(d_event.std(ddof=1)) if len(d_event) > 1 else math.nan,
        "power_threshold_pct": float(100 * POWER_Z * d_event.std(ddof=1) / math.sqrt(len(d_event)))
        if len(d_event) > 1 else math.nan,
        "p_boot": boot.get("p", math.nan),
        "delta_ci": [boot.get("ci_low", math.nan), boot.get("ci_high", math.nan)],
        "path_mean_r": vr.r.mean(axis=1).tolist(),
        "path_mean_delta": path_delta.tolist(),
        "paths_delta_positive": int((path_delta > 0).sum()),
        "skip_share": float(1.0 - entered.mean()),
        "skip_count_mean": float((1.0 - entered).sum(axis=1).mean()),
        "partial_share": float(vr.info["partial"].sum() / max(entered.sum(), 1.0)),
        "forced_share": float(vr.forced.sum() / max(entered.sum(), 1.0)),
        "stopped_share": float(vr.info["stopped"].sum() / max(entered.sum(), 1.0)),
        "distance_mean": float(np.mean(dist)) if dist.size else math.nan,
        "distance_median": float(np.median(dist)) if dist.size else math.nan,
        "mae_mean": float(np.mean(mae)) if mae.size else math.nan,
        "mae_median": float(np.median(mae)) if mae.size else math.nan,
        "win_rate": float((vr.r[entered == 1.0] > 0).mean()) if entered.sum() else math.nan,
        "q_auc_mean": float(np.nanmean(vr.auc["q"])) if vr.auc["q"] else math.nan,
        "q_auc_sd": float(np.nanstd(vr.auc["q"], ddof=1)) if len(vr.auc["q"]) > 1 else math.nan,
        "b_auc_mean": float(np.nanmean(vr.auc["b"])) if vr.auc["b"] else math.nan,
        "b_auc_sd": float(np.nanstd(vr.auc["b"], ddof=1)) if len(vr.auc["b"]) > 1 else math.nan,
    }
    if vr.strategy:
        out["strategy_sharpe_paths"] = [s["sharpe"] for s in vr.strategy]
        out["strategy_total_return_paths"] = [s["total_return"] for s in vr.strategy]
        out["strategy_max_drawdown_paths"] = [s["max_drawdown"] for s in vr.strategy]
        out["strategy_trades_paths"] = [s["n_trades"] for s in vr.strategy]
        out["strategy_turnover_paths"] = [s["turnover"] for s in vr.strategy]
    return out


def median_path(vr: VariantResult) -> int:
    order = np.argsort([s["sharpe"] for s in vr.strategy], kind="stable")
    return int(order[len(order) // 2])


# --------------------------------------------------------------------------------------------- logging


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()

    return {"commit": run("rev-parse", "--short", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


FROZEN_FILES = (
    "lab/models/dips.py",
    "lab/runner/reference.py",
    "lab/models/train.py",
    "lab/validation/stats.py",
    "lab/validation/splits.py",
    "research/dip-timing/study.py",
    "research/dip-timing/run_train.py",
    "research/dip-timing/run_validate.py",
    "research/dip-timing/freeze.py",
    "research/dip-timing/PLAN.md",
    "config/costs.yaml",
    "config/splits.yaml",
)


def code_hashes() -> dict[str, str]:
    return {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest() for p in FROZEN_FILES}


def config_hash() -> str:
    """SHA-256 over the frozen files' hashes and the interpretations (the frozen config hash)."""
    blob = json.dumps({"files": code_hashes(), "interpretations": INTERPRETATIONS}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, np.integer | np.bool_):
        return x.item()
    if isinstance(x, float | np.floating):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def with_spec(es: EventSet, **changes) -> dips.DipSpec:
    return replace(es.spec, **changes)
