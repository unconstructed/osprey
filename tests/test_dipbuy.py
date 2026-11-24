"""buy-the-dip (``lab/runner/dipbuy.py``, scouting only): the 365-day high, the dip ladder with its caps and limit fix,
the twins, the measures of section 8 and the rules D1-D3 of ``research/buy-the-dip/PLAN.md`` (the section 11 test
list).

Synthetic data and hand-built paths only: no catalog bar is read. Most hand-built paths hand the ladder a signal (I, H)
written in the test, so every boundary is an exact float, while the prices move the wallet's weights where a test
needs them to. The accounting and every decision are checked against ``one_pass``, an engine written here in coin
units and USDC cash that decides every order itself from section 5 (never the step's book or ``_simulate``'s weight
recursion), and the ladder's events against ``events_of``, a third statement of the rule from I and H alone.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from test_portfolio import random_panel, tamper_from

from lab.runner import dipbuy as DB
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner.reference import Costs

LIM = {"min_cash": 0.20, "max_coin": 0.60}  # Steady's limits (section 4; test_portfolio pins the real file)
COSTS = Costs.from_yaml(capital_usd=5000.0)
COSTS_2X = COSTS.stressed(2.0)
ZERO = replace(Costs.zero(), capital_usd=5000.0)
HEAVY = Costs(pool_fee_bps=30.0, aggregator_fee_bps=10.0, gas_usd_per_trade=2.0, capital_usd=5000.0)
D = 5000.0
DAY_US = 86_400_000_000
ULP_UP = math.inf
ULP_DOWN = -math.inf

# ------------------------------------------------------------------------------------------------ helpers


def days(n: int, start: str = "2017-01-02") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D", tz="UTC", name="ts")


def bars_on(index, closes, opens=None) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]]) if opens is None else np.asarray(opens, dtype=float)
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * 1.005,
            "low": np.minimum(o, c) * 0.995,
            "close": c,
            "volume": np.full(len(c), 1000.0),
        },
        index=pd.DatetimeIndex(index, name="ts"),
    )


def panel_on(index, btc, eth=None) -> pd.DataFrame:
    eth = btc if eth is None else eth
    return pf.make_panel({"BTC": bars_on(index, btc), "ETH": bars_on(index, eth)}, snapshot_id="hand")


def flat(n: int, index=None) -> pd.DataFrame:
    idx = days(n) if index is None else index
    return panel_on(idx, [100.0] * len(idx))


def path(n: int, base: float = 100.0, **at) -> list[float]:
    """``n`` closes at ``base``, with ``r<row>=price`` set from that row on (``r40=130``)."""
    out = [base] * n
    for key, price in sorted(((int(k[1:]), v) for k, v in at.items())):
        out[key:] = [price] * (n - key)
    return out


def hand_signal(index, i_close, high=None) -> pd.DataFrame:
    """A signal written in the test: I as given, I at each open the previous close's I (flat opens), H the 365-day
    high of I unless given."""
    i = np.asarray(i_close, dtype=float)
    hi = DB.recent_high(pd.DatetimeIndex(index).asi8, i) if high is None else np.asarray(high, dtype=float)
    opened = np.concatenate([[math.nan], i[:-1]])
    return pd.DataFrame({"I": i, "I_open": opened, "H": hi}, index=pd.DatetimeIndex(index, name="ts"))


def params(kind="dip", setting=(0.10, 0.10, 0.10, 0.25), s0=0.0, f=0.5, limits=LIM, total=None) -> dict:
    p = {"kind": kind, "s0": s0, "f": f, **limits}
    if kind == "dip":
        p.update(zip(("Y", "Z", "X", "M"), setting, strict=True))
    if total is not None:
        p["total"] = total
    return p


def run(panel, p, costs=ZERO, signal=None, **kw) -> pd.DataFrame:
    sig = DB.dip_signal(panel, p["f"]) if signal is None and p["kind"] == "dip" else signal
    return DB.dip_buy(p, panel, costs, sig, **kw)


def buys(res) -> list[dict]:
    return res.attrs["buys"].to_dict("records")


def nxt(x: float, toward: float) -> float:
    return float(np.nextafter(x, toward))


def events_of(i_close, high, setting) -> dict:
    """Section 5 written out a third time, close by close from I and H alone (never the wallet): the triggers (close,
    H*), the crossings (ladder, k from 1, close) and the re-arms."""
    y, z, x, m = setting
    k_lines = math.ceil(m / x - 1e-9)
    out = {"triggers": [], "crossings": [], "rearms": []}
    lines, crossed, running, armed = [], [], False, True
    for t in range(len(i_close)):
        i, hi = float(i_close[t]), float(high[t])
        if running and i >= hi:
            out["rearms"].append(t)
            running, armed = False, True
        elif running:
            for k in range(k_lines):
                if not crossed[k] and i <= lines[k]:
                    crossed[k] = True
                    out["crossings"].append((len(out["triggers"]) - 1, k + 1, t))
        if armed and i <= (1.0 - y) * hi:
            out["triggers"].append((t, hi))
            lines = [(1.0 - y) * hi * (1.0 - z) ** k for k in range(k_lines)]
            crossed = [i <= line for line in lines]
            out["crossings"] += [(len(out["triggers"]) - 1, k + 1, t) for k in range(k_lines) if crossed[k]]
            running, armed = True, False
    out["crossings"].sort(key=lambda e: (e[0], e[2], e[1]))
    return out


def one_pass(panel: pd.DataFrame, signal: pd.DataFrame | None, p: dict, costs: Costs) -> dict:
    """An independent engine: coin units and USDC cash, every order decided here from sections 4-6 (the ladder, the
    twins' schedules, the caps, the limit fix, one order per close, the last close never filled), each fill at the
    next open with its legs' costs (usd * rate(usd) + gas). Returns ret, the weights, the orders with their reasons and
    targets, the events and the amounts sent, capped, blocked and not filled."""
    n = len(panel)
    o = [panel[(a, "open")].to_numpy(dtype=float) for a in pf.ASSETS]
    c = [panel[(a, "close")].to_numpy(dtype=float) for a in pf.ASSETS]
    times = panel.index.asi8
    kind, s0, f = p["kind"], p["s0"], p["f"]
    mn, mc, h = p["min_cash"], p["max_coin"], 0.02
    first = (s0 * f, s0 * (1.0 - f))
    sched: dict[int, float] = {}
    if kind == "lump" and p["total"] > 0:
        sched[0] = p["total"]
    if kind == "dca" and p["total"] > 0:
        for j in range(12):
            later = [r for r in range(n) if times[r] - times[0] >= 30 * j * DAY_US]
            if later:
                sched.setdefault(later[0], []).append(p["total"] / 12)
        sched = {k: math.fsum(v) for k, v in sched.items()}
    if kind == "dip":
        y, z, x, m = (p[k] for k in ("Y", "Z", "X", "M"))
        k_lines = math.ceil(m / x - 1e-9)
        i_close, high = signal["I"].to_numpy(dtype=float), signal["H"].to_numpy(dtype=float)
    units, cash, value = [0.0, 0.0], costs.capital_usd, costs.capital_usd
    ret, weights = np.zeros(n), np.zeros((n, 2))
    out = {
        "orders": [],
        "reasons": [],
        "targets": [],
        "sent": 0.0,
        "capped": 0.0,
        "blocked": 0.0,
        "unfilled": 0.0,
    }
    out.update(triggers=[], crossings=[], rearms=[], bases=[])
    lad, armed, pending = None, True, None
    for t in range(n):
        w = [0.0, 0.0]
        if t > 0:
            before = value
            if pending is not None:
                vo = cash + units[0] * o[0][t] + units[1] * o[1][t]
                paid = 0.0
                for a in range(2):
                    usd = abs(pending[a] * vo - units[a] * o[a][t])
                    if usd > 0.0:
                        paid += usd * costs.rate(usd) + costs.gas_usd_per_trade
                left = vo - paid
                units = [pending[a] * left / o[a][t] for a in range(2)]
                cash = (1.0 - pending[0] - pending[1]) * left
            value = cash + units[0] * c[0][t] + units[1] * c[1][t]
            ret[t] = value / before - 1.0
            w = [units[a] * c[a][t] / value for a in range(2)]
            weights[t] = w
        pending = None
        base = first if t == 0 else w
        due = 0.0
        if kind == "dip":
            i, hi = i_close[t], high[t]
            now = []
            if lad is not None and i >= hi:
                out["rearms"].append(t)
                lad, armed = None, True
            elif lad is not None:
                now = [k for k in range(k_lines) if not lad["crossed"][k] and i <= lad["lines"][k]]
            if armed and i <= (1.0 - y) * hi:
                b = value * (1.0 - (base[0] + base[1]))
                pieces = [x * b] * (k_lines - 1) + [(m - (k_lines - 1) * x) * b]
                lad = {
                    "lines": [(1.0 - y) * hi * (1.0 - z) ** k for k in range(k_lines)],
                    "crossed": [False] * k_lines,
                }
                lad["pieces"] = pieces
                out["triggers"].append((t, float(hi)))
                out["bases"].append(b)
                armed = False
                now = [k for k in range(k_lines) if i <= lad["lines"][k]]
            for k in now:
                lad["crossed"][k] = True
                out["crossings"].append((len(out["triggers"]) - 1, k + 1, t))
            due = math.fsum(lad["pieces"][k] for k in now) if now else 0.0
        else:
            due = sched.get(t, 0.0)
        if t == n - 1:
            out["unfilled"] += due
            continue
        reason = target = None
        breach = t > 0 and (w[0] + w[1] > 1.0 - mn + 1e-9 or w[0] > mc + 1e-9 or w[1] > mc + 1e-9)
        if breach:
            lam = min(
                [1.0] + [(mc - h) / w[a] for a in range(2) if w[a] > 0] + [(1.0 - mn - h) / (w[0] + w[1])]
            )
            target, reason = (lam * w[0], lam * w[1]), "limit"
            out["blocked"] += due
        elif due > 0.0:
            want = due / value
            rooms = [want, 1.0 - mn - h - (base[0] + base[1])]
            rooms += [(mc - h - base[a]) / share for a, share in enumerate((f, 1.0 - f)) if share > 0.0]
            a_ = min(rooms)
            if a_ < want and a_ <= 1e-9:
                out["capped"] += due
                if t == 0 and s0 > 0:
                    target, reason = first, "first"
            else:
                target = (base[0] + f * a_, base[1] + (1.0 - f) * a_)
                reason = "first+buy" if t == 0 and s0 > 0 else "buy"
                out["sent"] += a_ * value
                out["capped"] += due - a_ * value
        elif t == 0 and s0 > 0:
            target, reason = first, "first"
        if target is not None:
            pending = target
            out["orders"].append(t)
            out["reasons"].append(reason)
            out["targets"].append(target)
    out["crossings"].sort(key=lambda e: (e[0], e[2], e[1]))
    out.update(ret=ret, weights=weights, value=value)
    return out


def same_as_one_pass(res, panel, p, costs, signal=None) -> dict:
    """Every order, reason, target, return, weight, event and amount of a run against :func:`one_pass`."""
    sig = signal if signal is not None or p["kind"] != "dip" else DB.dip_signal(panel, p["f"])
    want = one_pass(panel, sig, p, costs)
    assert res.attrs["orders"].tolist() == want["orders"]
    assert list(res.attrs["reasons"]) == want["reasons"]
    np.testing.assert_allclose(
        res.attrs["order_targets"].reshape(-1, 2), np.reshape(want["targets"], (-1, 2)), atol=1e-12
    )
    np.testing.assert_allclose(res["ret"].to_numpy(), want["ret"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(res[list(pf.WEIGHT_COLUMNS)].to_numpy(), want["weights"], rtol=0, atol=1e-12)
    b = res.attrs["buys"]
    for key in ("sent", "capped", "blocked", "unfilled"):
        assert math.fsum(b[key]) == pytest.approx(want[key], rel=1e-9, abs=1e-9), key
    if p["kind"] == "dip":
        ev = DB.run_events(res)
        assert ev["triggers"] == want["triggers"] and ev["crossings"] == want["crossings"]
        assert ev["rearms"] == want["rearms"]
        bases = [lad["base"] for lad in res.attrs["ladders"]]
        np.testing.assert_allclose(bases, want["bases"], rtol=1e-12)
    return want


# ------------------------------------------------------------------------------------------------ pinned values


def test_the_pinned_values_are_the_plan_s():
    assert (DB.Y_VALUES, DB.Z_VALUES, DB.X_VALUES, DB.M_VALUES) == (
        (0.10, 0.20, 0.30),
        (0.05, 0.10, 0.20),
        (0.10, 0.25),
        (0.25, 0.50, 1.00),
    )
    assert len(DB.SETTINGS) == 54 and len(set(DB.SETTINGS)) == 54  # section 7
    assert DB.SETTINGS[0] == (0.10, 0.05, 0.10, 0.25) and DB.SETTINGS[-1] == (0.30, 0.20, 0.25, 1.00)
    assert DB.STARTS == ((0.0, 0.5), (0.0, 0.75), (0.3, 0.5), (0.3, 0.75))
    assert (DB.DEPOSIT, DB.HEADROOM, DB.STEADY_MIN_CASH, DB.STEADY_MAX_COIN) == (5000.0, 0.02, 0.20, 0.60)
    assert (DB.HIGH_DAYS, DB.DCA_PIECES, DB.DCA_DAYS, DB.K_TOL) == (365, 12, 30, 1e-9)
    assert (DB.PERCENTILE, DB.TIE_TOL, DB.BOOM_MIN_WINDOWS) == (90.0, 1e-12, 12)
    assert DB.DESCRIBE_PERCENTILES == (10.0, 50.0, 90.0) and DB.BOOM_RANK_SOURCE == "KRAKEN"
    assert DB.KINDS == ("hold", "dip", "dca", "lump") and DB.TWINS == ("dca", "lump", "hold")
    assert DB.REASONS == ("first", "buy", "first+buy", "limit")
    for (
        s0,
        f,
    ) in DB.STARTS:  # every start passes check_targets with the Steady limits and h = 0.02 (section 4)
        pf.check_targets(*DB.start_targets(s0, f), **LIM, headroom=0.02)
    assert DB.start_targets(0.3, 0.75) == (0.3 * 0.75, 0.3 * (1.0 - 0.75)) and DB.start_targets(0.0, 0.5) == (
        0,
        0,
    )
    assert set(DB.READINGS_PINNED) >= {"high_window", "caps", "ordered", "twins", "knife", "d1_rank"}


def test_k_the_pieces_and_the_lines_by_hand():
    """K = ceil(M / X - 1e-9); pieces X B and the remainder (M - (K - 1) X) B (section 5: X 0.10, M 0.25 gives
    0.10, 0.10, 0.05); lines (1 - Y) H* (1 - Z)^(k - 1). Section 13's deepest lines: 10% below (one line) and 91%
    below (10 lines)."""
    want_k = {
        (0.10, 0.25): 3,
        (0.10, 0.50): 5,
        (0.10, 1.00): 10,
        (0.25, 0.25): 1,
        (0.25, 0.50): 2,
        (0.25, 1.00): 4,
    }
    for (x, m), k in want_k.items():
        assert DB.line_count(x, m) == k
        pieces = DB.ladder_pieces(DB.Setting(0.1, 0.1, x, m), 1000.0)
        assert pieces == [x * 1000.0] * (k - 1) + [(m - (k - 1) * x) * 1000.0]
        assert math.fsum(pieces) == pytest.approx(m * 1000.0, rel=1e-15)
    assert DB.ladder_pieces(DB.Setting(0.1, 0.1, 0.10, 0.25), 1.0) == [0.1, 0.1, 0.25 - 2 * 0.1]
    assert 0.25 - 2 * 0.1 == pytest.approx(0.05, abs=1e-16)
    assert (
        DB.line_count(0.03, 0.27) == 9 and 0.27 / 0.03 > 9.0
    )  # the 1e-9 keeps K from a tenth, near-empty line
    assert DB.line_count(0.10, 0.25 + 1e-12) == 3 and DB.line_count(0.10, 0.31) == 4
    lines = DB.ladder_lines(DB.Setting(0.30, 0.20, 0.10, 1.00), 1.0)
    assert len(lines) == 10 and lines == [(1.0 - 0.3) * 1.0 * (1.0 - 0.2) ** k for k in range(10)]
    assert 1.0 - lines[-1] == pytest.approx(0.906, abs=1e-3)  # 91% below the high
    assert DB.ladder_lines(DB.Setting(0.10, 0.20, 0.25, 0.25), 2.0) == [(1.0 - 0.1) * 2.0]
    assert (
        DB.ladder_lines(DB.Setting(0.2, 0.1, 0.1, 0.5), 3.0)[0] == (1.0 - 0.2) * 3.0
    )  # line 1 is the trigger


def test_parameters_are_refused_with_pinned_messages():
    flat_panel = flat(10)
    sig = hand_signal(flat_panel.index, [1.0] * 10)
    for bad, msg in (
        ({**params(), "kind": "ladder"}, "kind must be one of"),
        ({k: v for k, v in params().items() if k != "M"}, "needs Y, Z, X and M"),
        ({**params("hold"), "Y": 0.1}, "a hold run takes no"),
        (params("dca"), "total"),
        ({**params("hold"), "total": 5.0}, "a hold run takes no total"),
        ({**params("dca", total=-1.0)}, "total"),
        ({**params(), "Y": 1.0}, "Y"),
        ({**params(), "Z": 1.0}, "Z"),
        ({**params(), "X": 0.0}, "X"),
        ({**params(), "M": 1.5}, "M"),
        ({**params(), "s0": 1.0}, "s0"),
        ({**params(), "f": 1.2}, "f"),
        ({**params(), "max_coin": None}, "max_coin"),
        ({**params(), "s0": 0.9}, "break the limits"),
        ({**params(), "extra": 1}, "extra"),
    ):
        with pytest.raises(ValueError, match=msg):
            DB.dip_buy(bad, flat_panel, ZERO, sig)
    with pytest.raises(ValueError, match="needs the signal"):
        DB.dip_buy(params(), flat_panel, ZERO, None)
    with pytest.raises(ValueError, match="columns"):
        DB.dip_buy(params(), flat_panel, ZERO, sig.rename(columns={"H": "high"}))
    with pytest.raises(ValueError, match="exactly the bars' index"):
        DB.dip_buy(params(), flat_panel, ZERO, sig.iloc[1:])
    for col, value, msg in (
        ("I", 0.0, "I must be"),
        ("H", 0.5, "H must be"),
        ("I_open", -1.0, "I_open must"),
    ):
        bad = sig.copy()
        bad.iloc[3, bad.columns.get_loc(col)] = value
        with pytest.raises(ValueError, match=msg):
            DB.dip_buy(params(), flat_panel, ZERO, bad)
    with pytest.raises(ValueError, match="no row for 1 closes"):
        DB.window_signal(sig.iloc[:-1], flat_panel.index)
    for bad_times, msg in (([], "non-empty"), ([0, 0], "strictly increasing")):
        with pytest.raises(ValueError, match=msg):
            DB.recent_high(bad_times, [1.0] * len(bad_times))
    assert DB.parse_setting(0.1, 0.0, 1.0, 1.0) == (0.1, 0.0, 1.0, 1.0)


# ------------------------------------------------------------------------------------------------ the high and the index


def test_h_s_window_is_365_days_by_close_time():
    """Section 5: t - 365 days < close <= t. A high exactly 365 days back no longer counts; one 365 days minus one
    microsecond back still does (READINGS_PINNED['high_window']); close t itself counts."""
    year = 365 * DAY_US
    for back, counts in ((year, False), (year - 1, True), (year + 1, False), (364 * DAY_US, True)):
        times = [0, DAY_US, back]
        got = DB.recent_high(times, [2.0, 1.0, 0.5])
        assert got.tolist() == [2.0, 2.0, 2.0 if counts else 1.0], back
    assert DB.recent_high([0, 5], [1.0, 3.0]).tolist() == [1.0, 3.0]  # close t itself is included


def test_h_counts_calendar_days_across_a_missing_close():
    """Day 1 is missing: the high of day 0 counts at day 364 and not at day 365 (row 364 of the panel). A window of
    365 rows would still hold it there."""
    idx = days(400).delete(1)
    i = np.ones(len(idx))
    i[0] = 2.0
    hi = DB.recent_high(idx.asi8, i)
    row_364 = idx.get_loc(pd.Timestamp("2017-01-02", tz="UTC") + pd.Timedelta(days=364))
    assert hi[row_364] == 2.0 and hi[row_364 + 1] == 1.0 and row_364 == 363


@given(
    n=st.integers(2, 900),
    seed=st.integers(0, 2**32 - 1),
    gaps=st.lists(st.integers(1, 3), min_size=899, max_size=899),
)
def test_h_equals_a_brute_force_maximum(n, seed, gaps):
    rng = np.random.default_rng(seed)
    times = np.cumsum([0, *gaps[: n - 1]]) * DAY_US + rng.integers(0, 2) * 3600 * 10**6
    i = np.exp(np.cumsum(rng.normal(0, 0.05, n)))
    hi = DB.recent_high(times, i)
    for t in range(n):
        assert hi[t] == max(i[c] for c in range(t + 1) if times[c] > times[t] - 365 * DAY_US)


def test_dip_signal_is_protect_s_index_with_its_365_day_high():
    panel = random_panel(500, 3)
    sig = DB.dip_signal(panel, 0.75)
    ref = P.index_signal(panel, 0.75)
    assert tuple(sig.columns) == DB.SIGNAL_COLUMNS and sig.index.equals(panel.index)
    assert sig["I"].to_numpy().tobytes() == ref["I"].to_numpy().tobytes()
    assert np.array_equal(sig["I_open"].to_numpy(), ref["I_open"].to_numpy(), equal_nan=True)
    assert sig["H"].tolist() == DB.recent_high(panel.index.asi8, ref["I"].to_numpy()).tolist()
    rows = DB.window_signal(sig, panel.index[100:300])
    assert rows.equals(sig.iloc[100:300])


@given(seed=st.integers(0, 2**32 - 1), cut=st.integers(1, 299), f=st.sampled_from([0.5, 0.75]))
@example(seed=10, cut=269, f=0.75)  # a fall of more than 75%: 4 x close t stays under the year's high (#71)
@example(seed=1_845_724_919, cut=222, f=0.75)
def test_the_high_never_reads_the_future_and_reacts_to_the_present(seed, cut, f):
    """Tamper the future: I, I_open and H before the cut never move. Touch the present: both closes of row t times
    k = 2 H_t / I_t multiply I_t by k (I_t = I_(t-1) (f c_BTC,t / c_BTC,t-1 + (1 - f) c_ETH,t / c_ETH,t-1)), so I_t
    moves to twice the old high and becomes the new H_t; nothing before t moves."""
    panel = random_panel(300, seed)
    sig = DB.dip_signal(panel, f)
    other = DB.dip_signal(tamper_from(panel, cut, seed + 1), f)
    for col in DB.SIGNAL_COLUMNS:
        a, b = sig[col].to_numpy()[:cut], other[col].to_numpy()[:cut]
        assert np.array_equal(a, b, equal_nan=True), col
    touched = panel.copy()
    k = 2.0 * sig["H"].iloc[cut] / sig["I"].iloc[cut]
    for a in pf.ASSETS:
        touched.loc[touched.index[cut], (a, "close")] *= k
        touched.loc[touched.index[cut], (a, "high")] *= k
    touched.attrs = panel.attrs
    moved = DB.dip_signal(touched, f)
    assert moved["I"].iloc[cut] != sig["I"].iloc[cut] and moved["H"].iloc[cut] == moved["I"].iloc[cut]
    assert moved["H"].iloc[cut] != sig["H"].iloc[cut]
    assert moved.iloc[:cut].equals(sig.iloc[:cut])


# ------------------------------------------------------------------------------------------------ the trigger


@pytest.mark.parametrize("y", [0.10, 0.20, 0.30])
def test_the_trigger_fires_exactly_on_its_float_and_not_one_ulp_above(y):
    n = 8
    idx = days(n)
    line = (1.0 - y) * 1.0
    for value, fires in ((line, True), (nxt(line, ULP_UP), False), (nxt(line, ULP_DOWN), True)):
        sig = hand_signal(idx, [1.0, 1.0, 1.0, value, value, value, value, value], [1.0] * n)
        res = run(flat(n), params(setting=(y, 0.10, 0.10, 0.25)), signal=sig)
        assert [lad["start"] for lad in res.attrs["ladders"]] == ([3] if fires else []), value
        assert res.attrs["orders"].tolist() == ([3] if fires else [])


def test_the_trigger_fixes_h_star_and_the_base_from_the_cash_at_the_trigger():
    """The trigger at close 4 (I 0.85 under 0.9 H): H* = 1, B = V_4 times the cash weight at close 4; with a 30%
    start the base is the USDC after the first buy."""
    n = 12
    idx = days(n)
    sig = hand_signal(idx, [1.0] * 4 + [0.85] * 8, [1.0] * n)
    btc = path(n, r2=120.0)
    panel = panel_on(idx, btc, path(n))
    res = run(panel, params(s0=0.3, setting=(0.10, 0.10, 0.10, 0.25)), signal=sig)
    lad = res.attrs["ladders"][0]
    w = res[list(pf.WEIGHT_COLUMNS)].to_numpy()[4]
    v = P.wallet_values(res["ret"].to_numpy(), D)[4]
    assert lad["start"] == 4 and lad["high"] == 1.0
    assert lad["base"] == pytest.approx(v * (1.0 - (w[0] + w[1])), rel=1e-15)
    assert lad["lines"] == [0.9, 0.9 * 0.9, 0.9 * 0.9**2] and lad["crossed"] == [4, None, None]
    assert lad["pieces"] == [0.1 * lad["base"], 0.1 * lad["base"], (0.25 - 0.2) * lad["base"]]


def test_a_trigger_on_close_0_with_a_30_percent_start_uses_the_cash_after_the_first_buy():
    """B = (1 - s0) D at close 0 (section 5); the first buy and the ladder's piece are one order."""
    n = 6
    idx = days(n)
    sig = hand_signal(idx, [1.0] * n, [1.2] * n)  # I 1.0 <= 0.9 x 1.2 at close 0 already
    res = run(flat(n), params(s0=0.30, f=0.5, setting=(0.10, 0.10, 0.10, 0.25)), signal=sig)
    lad = res.attrs["ladders"][0]
    assert lad["start"] == 0 and lad["base"] == D * (1.0 - (0.3 * 0.5 + 0.3 * (1.0 - 0.5)))
    assert lad["base"] == pytest.approx((1.0 - 0.3) * D, rel=1e-15)
    assert lad["crossed"] == [0, None, None]  # 1.0 <= 1.08, 1.0 > 0.972
    assert res.attrs["orders"].tolist() == [0] and list(res.attrs["reasons"]) == ["first+buy"]
    a = 0.1 * lad["base"] / D
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.15 + 0.5 * a, 0.15 + 0.5 * a]])


# ------------------------------------------------------------------------------------------------ the lines


def test_a_gap_through_three_lines_is_one_order_of_three_pieces():
    n = 10
    idx = days(n)
    sig = hand_signal(idx, [1.0, 1.0, 0.7, 0.7, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6], [1.0] * n)
    res = run(flat(n), params(setting=(0.10, 0.10, 0.10, 0.25)), signal=sig)
    lad = res.attrs["ladders"][0]
    assert lad["crossed"] == [2, 2, 2] and res.attrs["orders"].tolist() == [2]
    row = buys(res)[0]
    assert row["lines"] == 3 and row["due"] == math.fsum([0.1 * D, 0.1 * D, (0.25 - 0.2) * D]) == row["sent"]
    a = row["due"] / D
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.5 * a, 0.5 * a]])


def test_each_line_is_relative_to_the_one_before_and_crossed_once():
    """Z is a fall below the previous line: 0.9, 0.81, 0.729 at Z 0.10. A line exactly at I is crossed; one ulp
    above it is not; a line crossed once is never bought again."""
    n = 14
    idx = days(n)
    l2, l3 = 0.9 * 0.9, 0.9 * 0.9**2
    i = [1.0, 0.95, 0.9, 0.85, nxt(l2, ULP_UP), l2, 0.9, l2, l3, l3, 0.5, 0.5, 0.5, 0.5]
    res = run(flat(n), params(setting=(0.10, 0.10, 0.10, 1.0)), signal=hand_signal(idx, i, [1.0] * n))
    lad = res.attrs["ladders"][0]
    assert lad["crossed"][:3] == [2, 5, 8] and lad["crossed"][3:6] == [10, 10, 10]
    assert res.attrs["orders"].tolist() == [2, 5, 8, 10]
    assert [r["lines"] for r in buys(res)] == [1, 1, 1, 3]


def test_m_caps_the_ladder_and_k_s_remainder_is_the_last_piece():
    """X 0.25, M 0.50: two pieces of 0.25 B and nothing below the second line; X 0.10, M 0.25: 10%, 10%, 5%."""
    n = 10
    idx = days(n)
    sig = hand_signal(idx, [1.0] + [0.1] * (n - 1), [1.0] * n)
    for (x, m), want in (
        ((0.25, 0.50), [0.25 * D, (0.5 - 0.25) * D]),
        ((0.10, 0.25), [0.1 * D] * 2 + [(0.25 - 0.2) * D]),
    ):
        res = run(flat(n), params(setting=(0.10, 0.05, x, m)), signal=sig)
        assert res.attrs["ladders"][0]["pieces"] == want
        assert buys(res)[0]["due"] == math.fsum(want) and len(buys(res)) == 1


# ------------------------------------------------------------------------------------------------ re-arming


def test_re_arming_exactly_at_the_high_and_not_one_ulp_below():
    n = 12
    idx = days(n)
    for value, rearms in ((1.0, True), (nxt(1.0, ULP_DOWN), False)):
        i = [1.0, 0.85, 0.85, value, 1.0, 1.0, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85]
        hi = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        res = run(flat(n), params(setting=(0.10, 0.10, 0.10, 0.25)), signal=hand_signal(idx, i, hi))
        ladders = res.attrs["ladders"]
        assert ladders[0]["rearm"] == (3 if rearms else 4)
        assert [lad["start"] for lad in ladders] == [1, 6]


def test_a_re_arm_drops_the_lines_not_crossed_and_the_next_base_is_the_cash_left():
    n = 16
    idx = days(n)
    i = [1.0, 0.85, 0.85, 1.0, 1.0, 0.8, 0.8, 0.8] + [0.8] * 8
    hi = [1.0] * 4 + [1.0] * 12
    res = run(flat(n), params(setting=(0.10, 0.10, 0.10, 0.25)), signal=hand_signal(idx, i, hi))
    first, second = res.attrs["ladders"]
    assert first["crossed"] == [1, None, None] and first["rearm"] == 3
    v = P.wallet_values(res["ret"].to_numpy(), D)
    w = res[list(pf.WEIGHT_COLUMNS)].to_numpy()
    assert second["start"] == 5 and second["base"] == pytest.approx(v[5] * (1.0 - w[5].sum()), rel=1e-15)
    assert second["base"] == pytest.approx(D - 0.1 * D, rel=1e-15)  # flat prices, zero costs: the cash left
    assert second["crossed"] == [5, 5, None]  # 0.8 under 0.9 and 0.81, above 0.729
    ev = DB.run_events(res)
    assert ev == events_of(i, hi, (0.10, 0.10, 0.10, 0.25))


def test_no_line_is_crossed_on_a_re_arm_close_and_no_trigger_follows_on_it():
    n = 8
    idx = days(n)
    i = [1.0, 0.85, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    hi = [1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5]  # I == H at close 5: re-arm, never a crossing or a trigger
    res = run(flat(n), params(setting=(0.10, 0.10, 0.10, 1.0)), signal=hand_signal(idx, i, hi))
    (lad,) = res.attrs["ladders"]
    assert lad["rearm"] == 5 and all(c in (1, 2, None) for c in lad["crossed"])
    assert DB.recompute_events(i, hi, DB.Setting(0.10, 0.10, 0.10, 1.0)) == DB.run_events(res)


# ------------------------------------------------------------------------------------------------ caps and limit fixes


def _big_buy(s0, f, n=8):
    """All four 25% lines crossed at close 2 (I 0.3 under the 0.9 H trigger): a buy of B = the cash."""
    idx = days(n)
    return (
        flat(n),
        hand_signal(idx, [1.0, 1.0] + [0.3] * (n - 2), [1.0] * n),
        params(setting=(0.10, 0.05, 0.25, 1.00), s0=s0, f=f),
    )


@pytest.mark.parametrize(
    ("s0", "f", "binds"),
    [(0.3, 0.75, "BTC"), (0.3, 0.25, "ETH"), (0.0, 0.5, "cash")],
)
def test_each_cap_binding_alone_cuts_the_buy_to_the_largest_amount_that_keeps_it(s0, f, binds):
    panel, sig, p = _big_buy(s0, f)
    res = run(panel, p, signal=sig)
    w0 = DB.start_targets(s0, f)
    row = buys(res)[-1]
    u = row["due"] / D
    rooms = {"BTC": (0.58 - w0[0]) / f, "ETH": (0.58 - w0[1]) / (1.0 - f), "cash": 0.78 - (w0[0] + w0[1])}
    assert min(rooms, key=rooms.get) == binds and rooms[binds] < u
    a = min(rooms.values())
    target = res.attrs["order_targets"][-1]
    np.testing.assert_allclose(target, [w0[0] + f * a, w0[1] + (1.0 - f) * a], rtol=0, atol=1e-15)
    side = {"BTC": target[0], "ETH": target[1], "cash": 1.0 - target.sum()}[binds]
    assert side == pytest.approx(0.22 if binds == "cash" else 0.58, abs=1e-15)
    assert row["sent"] == pytest.approx(a * D, rel=1e-15) and row["capped"] == pytest.approx(
        row["due"] - a * D, rel=1e-15
    )
    pf.check_targets(*target, **LIM, headroom=0.02)
    same_as_one_pass(res, panel, p, ZERO, sig)


def test_r1_no_order_when_no_positive_amount_fits_and_the_whole_amount_is_capped():
    """After a capped buy the wallet sits exactly at 58% BTC (flat prices): the next line orders nothing, and its
    whole piece is capped; the ladder never sells. With BTC up a little (59%, inside h but not past the 60% limit) the
    same: no order, no limit fix."""
    n = 10
    idx = days(n)
    sig = hand_signal(idx, [1.0, 1.0, 0.7, 0.7, 0.7, 0.5, 0.5, 0.5, 0.5, 0.5], [1.0] * n)
    p = params(setting=(0.10, 0.10, 0.25, 1.00), s0=0.3, f=0.75)
    for btc in (path(n), path(n, r4=101.5)):
        panel = panel_on(idx, btc, path(n))
        res = run(panel, p, signal=sig)
        assert res.attrs["orders"].tolist() == [0, 2] and list(res.attrs["reasons"]) == ["first", "buy"]
        last = buys(res)[-1]
        assert last["close"] == 5 and last["sent"] == 0.0 and last["capped"] == last["due"] > 0.0
        w = res["w_BTC"].iloc[5]
        assert 0.58 - 1e-15 <= w < 0.60
        same_as_one_pass(res, panel, p, ZERO, sig)


def test_a_btc_only_or_eth_only_split_caps_its_one_coin():
    """f = 1 buys BTC only and f = 0 ETH only: the other coin's cap never binds (it gets nothing)."""
    for f, coin in ((1.0, 0), (0.0, 1)):
        panel, sig, p = _big_buy(0.3, f)
        res = run(panel, p, signal=sig)
        target = res.attrs["order_targets"][-1]
        assert target[coin] == pytest.approx(0.58, abs=1e-15) and target[1 - coin] == 0.0
        same_as_one_pass(res, panel, p, ZERO, sig)


def test_a_first_buy_whose_ladder_piece_is_capped_to_nothing_is_the_first_buy_alone():
    """A 78% start (39% / 39%) has cash exactly at 22%: a trigger at close 0 orders the first buy only, and the whole
    piece is capped (R1)."""
    n = 6
    idx = days(n)
    sig = hand_signal(idx, [1.0] * n, [1.2] * n)
    res = run(flat(n), params(s0=0.78, f=0.5, setting=(0.10, 0.10, 0.10, 0.25)), signal=sig)
    assert list(res.attrs["reasons"]) == ["first"] and res.attrs["orders"].tolist() == [0]
    np.testing.assert_array_equal(res.attrs["order_targets"], [[0.78 * 0.5, 0.78 * 0.5]])
    (row,) = buys(res)
    assert row["capped"] == row["due"] > 0 and row["sent"] == 0.0 and row["reason"] == "first"


def test_the_plans_reset_at_a_buy_back():
    """LadderPlan.reset drops a running ladder (marked dropped) and arms afresh; with nothing running it only arms.
    The twins' plans ignore a buy-back."""
    plan = DB.LadderPlan(DB.Setting(0.1, 0.1, 0.1, 0.25), [1.0, 0.8, 0.8], [1.0, 1.0, 1.0])
    plan.reset(0)
    assert plan.armed and plan.current is None and plan.ladders == []
    assert plan.due(1, (0.0, 0.0), 100.0)[0] == math.fsum([10.0, 10.0])  # 0.8 under 0.9 and 0.81
    assert not plan.armed
    plan.reset(2)
    assert plan.armed and plan.current is None and plan.ladders[0]["dropped"] == 2
    twin = DB.ScheduledPlan({3: [5.0, 6.0]})
    assert twin.reset(1) is None and twin.due(3, (0, 0), 1.0) == (11.0, -1, [0, 1])
    assert twin.due(2, (0, 0), 1.0) == (0.0, -1, [])


def test_a_twin_behind_a_brake_skips_the_pieces_due_while_stopped():
    n = 120
    c = [100.0] * 5 + [100.0 - 4.0 * k for k in range(1, 11)] + [60.0] * 105
    panel = panel_on(days(n), c)
    brake = P.parse_brake("A", 0.10, "wait30", "counts")
    res = run(
        panel,
        params("dca", s0=0.3, total=1200.0),
        COSTS,
        brake=brake,
        brake_signal=P.index_signal(panel, 0.5),
    )
    stop, back = res.attrs["stops"].tolist(), res.attrs["buybacks"].tolist()
    assert len(stop) == 1 and len(back) == 1
    asked = set(res.attrs["asked"].tolist())
    sent = [t for t, r in zip(res.attrs["orders"], res.attrs["reasons"], strict=True) if r == "buy"]
    assert all(t in asked for t in sent) and not any(stop[0] <= t <= back[0] for t in sent)
    DB.check_values(res)
    P.check_book(res, panel, COSTS)


def test_a_cap_leaving_only_round_off_sends_nothing():
    """READINGS_PINNED['caps']: a cap that leaves at most LIMIT_TOL of the wallet sends no order."""
    assert DB._cap((0.58 - 5e-10, 0.1), 0.5, 1.0, 0.2, 0.6) == pytest.approx(5e-10, abs=1e-16)
    n = 8
    idx = days(n)
    sig = hand_signal(idx, [1.0, 1.0, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85], [1.0] * n)
    p = params(setting=(0.10, 0.10, 0.10, 0.25), s0=0.3, f=1.0)
    for start_btc, sends in ((0.58 - 2e-9, True), (0.58 - 5e-10, False)):
        # a BTC-only wallet bought to start_btc at close 0 by a first buy of s0 = start_btc (f = 1)
        p0 = {**p, "s0": start_btc}
        res = run(flat(n), p0, signal=sig)
        assert ("buy" in list(res.attrs["reasons"])) == sends, start_btc


def test_lambda_by_hand_and_the_fix_replaces_a_due_buy_and_consumes_its_pieces():
    """BTC x10 from close 3 takes the 30% start to 63.8% BTC: a breach at close 3. A line crossed at close 3 is
    blocked (its piece consumed, never bought later); the fix scales both coins by lambda = 0.58 / w_BTC."""
    n = 10
    idx = days(n)
    panel = panel_on(idx, path(n, r3=1000.0), path(n))
    sig = hand_signal(idx, [1.0, 1.0, 1.0, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85], [1.0] * n)
    p = params(setting=(0.10, 0.10, 0.10, 0.25), s0=0.3, f=0.5)
    res = run(panel, p, signal=sig)
    w = res[list(pf.WEIGHT_COLUMNS)].to_numpy()[3]
    assert w[0] > 0.6
    lam = min(1.0, 0.58 / w[0], 0.58 / w[1], 0.78 / (w[0] + w[1]))
    assert lam == 0.58 / w[0] == DB.lambda_fix(w, 0.2, 0.6)
    assert res.attrs["orders"].tolist() == [0, 3] and list(res.attrs["reasons"]) == ["first", "limit"]
    np.testing.assert_array_equal(res.attrs["order_targets"][1], [lam * w[0], lam * w[1]])
    (row,) = buys(res)
    assert row["close"] == 3 and row["blocked"] == row["due"] == 0.1 * res.attrs["ladders"][0]["base"]
    assert row["sent"] == row["capped"] == 0.0 and res.attrs["ladders"][0]["crossed"] == [3, None, None]
    m = DB.run_measures(res, ZERO, sig)
    assert m["blocked_usd"] == row["due"] and m["ordered_usd"] == row["due"] and m["orders"] == 0
    same_as_one_pass(res, panel, p, ZERO, sig)


def test_lambda_by_the_cash_floor_and_breaches_judged_at_the_limits():
    assert DB.lambda_fix((0.45, 0.40), 0.2, 0.6) == 0.78 / (0.45 + 0.40)
    assert DB.lambda_fix((0.0, 0.7), 0.2, 0.6) == 0.58 / 0.7
    assert DB.lambda_fix((0.0, 0.0), 0.2, 0.6) == 1.0
    n = 8
    idx = days(n)
    sig = hand_signal(idx, [1.0] * n, [1.0] * n)
    p = params("hold", s0=0.3, f=0.75)
    # BTC 0.225 grows to exactly 0.60 (no breach: judged at the limit) and to 0.61 (a breach) at close 3
    for factor, fixes in ((0.6 * 0.775 / (0.225 * 0.4), False), (0.61 * 0.775 / (0.225 * 0.39), True)):
        panel = panel_on(idx, path(n, r3=100.0 * factor), path(n))
        res = run(panel, p, signal=sig)
        assert ("limit" in list(res.attrs["reasons"])) == fixes, factor


def test_a_line_crossed_at_the_last_close_is_not_filled():
    n = 6
    idx = days(n)
    sig = hand_signal(idx, [1.0] * 5 + [0.7], [1.0] * n)
    res = run(flat(n), params(setting=(0.10, 0.10, 0.10, 0.25)), signal=sig)
    assert res.attrs["orders"].tolist() == [] and res.attrs["ladders"][0]["crossed"] == [5, 5, 5]
    (row,) = buys(res)
    assert row["unfilled"] == row["due"] > 0 and row["sent"] == row["capped"] == row["blocked"] == 0.0
    m = DB.run_measures(res, ZERO, sig)
    assert m["ordered_usd"] == 0.0 and m["unfilled_lines"] == 3 and m["unfilled_usd"] == row["due"]
    assert math.isnan(m["first_order_days"]) and m["delta"] == 0.0


# ------------------------------------------------------------------------------------------------ the twins


def test_dca_s_twelve_closes_in_calendar_days_across_a_missing_close():
    idx = days(400).delete(30)  # day 30 is missing: piece 1 at day 31 (row 30)
    got = DB.dca_closes(idx.asi8)
    want = [None] * 12
    for j in range(12):
        want[j] = next(r for r, ts in enumerate(idx) if ts - idx[0] >= pd.Timedelta(days=30 * j))
    assert got == want and got[:3] == [0, 30, 59]
    assert DB.dca_closes(days(200).asi8)[7:] == [None] * 5


def test_the_dca_twin_spreads_the_total_in_twelve_pieces():
    n = 400
    idx = days(n).delete(30)
    panel = flat(len(idx), idx)
    p = params("dca", s0=0.0, total=1200.0)
    res = run(panel, p)
    closes = DB.dca_closes(idx.asi8)
    assert res.attrs["orders"].tolist() == closes and set(res.attrs["reasons"]) == {"buy"}
    assert [r["due"] for r in buys(res)] == [100.0] * 12
    DB.check_twin(res, 1200.0)
    same_as_one_pass(res, panel, p, ZERO)
    short = run(flat(200), params("dca", total=1200.0))  # pieces 7-11 have no close: not filled
    assert short.attrs["lost"] == 500.0 and DB.run_measures(short, ZERO)["unfilled_usd"] == 500.0
    DB.check_twin(short, 1200.0)
    shut = run(flat(331), params("dca", total=1200.0))  # piece 11 at the last close: not filled
    assert buys(shut)[-1]["unfilled"] == 100.0 and shut.attrs["lost"] == 0.0
    DB.check_twin(shut, 1200.0)


def test_the_lump_twin_buys_the_total_at_close_0_with_the_first_buy():
    p = params("lump", s0=0.3, f=0.75, total=700.0)
    res = run(flat(10), p)
    assert res.attrs["orders"].tolist() == [0] and list(res.attrs["reasons"]) == ["first+buy"]
    a = 700.0 / D
    np.testing.assert_array_equal(
        res.attrs["order_targets"], [[0.3 * 0.75 + 0.75 * a, 0.3 * 0.25 + 0.25 * a]]
    )
    DB.check_twin(res, 700.0)


def test_a_dip_run_with_no_order_has_twins_equal_to_hold_bit_for_bit():
    panel = random_panel(300, 11, (0.03, 0.04))
    p = params(setting=(0.30, 0.10, 0.10, 0.25), s0=0.3, f=0.5)
    sig = hand_signal(panel.index, [1.0] * 300, [1.0] * 300)
    dip = run(panel, p, COSTS, signal=sig)
    assert DB.run_measures(dip, COSTS, sig)["ordered_usd"] == 0.0
    hold = run(panel, params("hold", s0=0.3, f=0.5), COSTS)
    for kind in ("dca", "lump"):
        twin = run(panel, params(kind, s0=0.3, f=0.5, total=0.0), COSTS)
        DB.check_twin(twin, 0.0, hold)
        assert twin.equals(hold) and twin.attrs["orders"].tolist() == hold.attrs["orders"].tolist()
    for col in dip.columns:
        assert dip[col].to_numpy().tobytes() == hold[col].to_numpy().tobytes()


# ------------------------------------------------------------------------------------------------ identities


@given(
    seed=st.integers(0, 2**32 - 1),
    f=st.sampled_from([0.5, 0.75]),
    costs=st.sampled_from([ZERO, COSTS, HEAVY]),
)
def test_hold_without_a_breach_is_portfolio_rebalance_with_band_1_bit_for_bit(seed, f, costs):
    panel = random_panel(200, seed, (0.01, 0.01), (0.0, 0.0))
    hold = run(panel, params("hold", s0=0.3, f=f), costs)
    assert set(hold.attrs["reasons"]) == {"first"}  # no breach on these quiet panels
    ref = pf.rebalance(
        {"w_btc": 0.3 * f, "w_eth": 0.3 * (1.0 - f), "band": 1.0, "every": 1, **LIM, "headroom": 0.02},
        panel,
        costs,
    )
    for col in ref.columns:
        assert hold[col].to_numpy().tobytes() == ref[col].to_numpy().tobytes(), col
    assert hold.attrs["orders"].tolist() == ref.attrs["orders"].tolist() == [0]


@given(seed=st.integers(0, 2**32 - 1), s0=st.sampled_from([0.0, 0.3]), f=st.sampled_from([0.5, 0.75]))
def test_a_dip_run_that_never_triggers_is_hold_bit_for_bit(seed, s0, f):
    panel = random_panel(250, seed)
    dip = run(panel, params(setting=(0.95, 0.1, 0.1, 1.0), s0=s0, f=f), COSTS)
    assert dip.attrs["ladders"] == []
    hold = run(panel, params("hold", s0=s0, f=f), COSTS)
    for col in hold.columns:
        assert dip[col].to_numpy().tobytes() == hold[col].to_numpy().tobytes(), col
    assert list(dip.attrs["reasons"]) == list(hold.attrs["reasons"])


@given(seed=st.integers(0, 2**32 - 1), setting=st.sampled_from(DB.SETTINGS), s0=st.sampled_from([0.0, 0.3]))
def test_when_the_ladder_buys_does_not_depend_on_costs_or_the_wallet_size(seed, setting, s0):
    """The triggers, crossings and re-arms (events_hash) are equal at zero cost, 1x, 2x and five wallet sizes; with
    a ladder that never nears a limit (M 0.25 from an all-USDC start) the orders and reasons are equal too."""
    panel = random_panel(400, seed, (0.05, 0.06))
    sig = DB.dip_signal(panel, 0.5)
    p = params(setting=setting, s0=s0)
    runs = [
        run(panel, p, c, sig)
        for c in (
            ZERO,
            COSTS,
            COSTS_2X,
            *(replace(COSTS, capital_usd=v) for v in (500.0, 2000.0, 20_000.0, 50_000.0, 1e6)),
        )
    ]
    assert len({DB.events_hash(r) for r in runs}) == 1
    if s0 == 0.0 and setting.M == 0.25:
        assert len({DB.orders_hash(r) for r in runs}) == 1


# ------------------------------------------------------------------------------------------------ the one-pass engine and accounting

KINDS_DRAWN = st.sampled_from(["dip", "dip", "dip", "dca", "lump", "hold"])


@given(
    seed=st.integers(0, 2**32 - 1),
    n=st.integers(60, 500),
    vols=st.tuples(st.sampled_from([0.02, 0.05, 0.09]), st.sampled_from([0.02, 0.05, 0.09])),
    kind=KINDS_DRAWN,
    setting=st.sampled_from(DB.SETTINGS),
    start=st.sampled_from(DB.STARTS + ((0.3, 0.25), (0.1, 1.0))),
    costs=st.sampled_from([ZERO, COSTS, COSTS_2X, HEAVY]),
    total=st.sampled_from([0.0, 800.0, 4000.0]),
)
@example(
    seed=5,
    n=500,
    vols=(0.09, 0.09),
    kind="dip",
    setting=DB.Setting(0.1, 0.05, 0.1, 1.0),
    start=(0.0, 0.5),
    costs=COSTS,
    total=0.0,
)
@example(
    seed=8,
    n=500,
    vols=(0.09, 0.05),
    kind="dip",
    setting=DB.Setting(0.1, 0.05, 0.25, 1.0),
    start=(0.3, 0.75),
    costs=HEAVY,
    total=0.0,
)
@example(
    seed=2,
    n=400,
    vols=(0.09, 0.09),
    kind="dca",
    setting=DB.SETTINGS[0],
    start=(0.3, 0.75),
    costs=COSTS,
    total=4000.0,
)
def test_every_run_equals_an_independent_one_pass_engine_and_its_book(
    seed, n, vols, kind, setting, start, costs, total
):
    """Every order, reason and target vector, every return and weight (1e-12), every event and amount against
    ``one_pass``; the step's book against the run's own returns; protect.check_book (coin units and cash with each
    order's own target vector); every order through check_targets (R1)."""
    panel = random_panel(n, seed, vols)
    s0, f = start
    p = params(kind, setting=setting, s0=s0, f=f, total=total if kind in ("dca", "lump") else None)
    sig = DB.dip_signal(panel, f) if kind == "dip" else None
    res = run(panel, p, costs, sig)
    same_as_one_pass(res, panel, p, costs, sig)
    DB.check_values(res)
    DB.check_order_targets(res, LIM)
    P.check_book(res, panel, costs)
    if kind == "dip":
        DB.check_events(res, sig)
        assert DB.run_events(res) == events_of(sig["I"].to_numpy(), sig["H"].to_numpy(), setting)


BUSY = {
    "seed": 5,
    "n": 500,
    "vols": (0.09, 0.09),
    "setting": DB.Setting(0.1, 0.05, 0.1, 1.0),
    "start": (0.3, 0.75),
}


def _busy():
    panel = random_panel(BUSY["n"], BUSY["seed"], BUSY["vols"])
    s0, f = BUSY["start"]
    return panel, params(setting=BUSY["setting"], s0=s0, f=f)


def test_the_busy_run_triggers_crosses_re_arms_caps_and_fixes():
    """The pinned busy run that the tamper tests anchor on holds every kind of event."""
    panel, p = _busy()
    res = run(panel, p, COSTS)
    ev = DB.run_events(res)
    b = res.attrs["buys"]
    assert len(ev["triggers"]) >= 2 and len(ev["rearms"]) >= 1 and len(ev["crossings"]) >= 6
    assert (b["capped"] > 0).any() and "limit" in list(res.attrs["reasons"])


def _anchors(res) -> list[int]:
    ev = DB.run_events(res)
    marks = {t for t, _ in ev["triggers"]} | {c for _, _, c in ev["crossings"]} | set(ev["rearms"])
    marks |= {int(t) for t, r in zip(res.attrs["orders"], res.attrs["reasons"], strict=True) if r == "limit"}
    return sorted({m + d for m in marks for d in (0, 1) if 1 <= m + d < len(res) - 1})


def _tamper_check(panel, p, cut, seed, costs=COSTS):
    sig = DB.dip_signal(panel, p["f"])
    res = run(panel, p, costs, sig)
    other_panel = tamper_from(panel, cut, seed)
    other_sig = DB.dip_signal(other_panel, p["f"])
    other = run(other_panel, p, costs, other_sig)
    for col in res.columns:
        assert np.array_equal(res[col].to_numpy()[:cut], other[col].to_numpy()[:cut]), col
    assert sig.iloc[:cut].equals(other_sig.iloc[:cut])

    def before(r):
        ev = DB.run_events(r)
        return (
            [e for e in ev["triggers"] if e[0] < cut],
            [e for e in ev["crossings"] if e[2] < cut],
            [e for e in ev["rearms"] if e < cut],
            [(t, str(x)) for t, x in zip(r.attrs["orders"], r.attrs["reasons"], strict=True) if t < cut],
            r.attrs["order_targets"][r.attrs["orders"] < cut].tobytes(),
            [tuple(x) for x in r.attrs["buys"].to_numpy().tolist() if x[0] < cut],
        )

    assert before(res) == before(other)
    lines = {lad["start"]: lad["lines"] for lad in res.attrs["ladders"] if lad["start"] < cut}
    assert lines == {lad["start"]: lad["lines"] for lad in other.attrs["ladders"] if lad["start"] < cut}


def test_no_look_ahead_at_every_anchor_of_the_busy_run():
    """Tamper the future from every trigger, crossing, re-arm and limit-fix close of the busy run, and the close
    after each: nothing decided or booked before the cut moves."""
    panel, p = _busy()
    anchors = _anchors(run(panel, p, COSTS))
    assert len(anchors) >= 20
    for i, cut in enumerate(anchors):
        _tamper_check(panel, p, cut, 1000 + i)


@given(
    seed=st.integers(0, 2**32 - 1),
    setting=st.sampled_from(DB.SETTINGS),
    start=st.sampled_from(DB.STARTS),
    data=st.data(),
)
def test_no_look_ahead_with_cuts_at_the_run_s_own_events(seed, setting, start, data):
    panel = random_panel(260, seed, (0.07, 0.08))
    p = params(setting=setting, s0=start[0], f=start[1])
    anchors = _anchors(run(panel, p, COSTS))
    cut = data.draw(st.sampled_from(anchors) if anchors and data.draw(st.booleans()) else st.integers(1, 258))
    _tamper_check(panel, p, cut, seed + 7)


# ------------------------------------------------------------------------------------------------ behind a brake


def test_behind_a_brake_the_ladder_is_not_asked_while_stopped_and_starts_armed_afresh():
    """Through protect.run_overlay with line A at 10% and a 30-day buy-back: the step is not asked from the stop close
    to the buy-back close (the spy, attrs['asked']), crosses no line then although I falls through every line, and
    after the buy-back starts a new ladder with a new H* and base; its book holds the engine's weights at every
    close it is asked (the replay of the stop and the buy-back), and the accounting holds."""
    n = 120
    c = [100.0] * n
    for t in range(5, 15):
        c[t] = 100.0 - 4.0 * (t - 4)
    c[15:60] = [60.0] * 45
    c[60:90] = [60.0 + 2.0 * (t - 59) for t in range(60, 90)]
    c[90:] = [120.0] * 30
    idx = days(n)
    panel = panel_on(idx, c)
    p = params(setting=(0.10, 0.05, 0.10, 1.0), s0=0.3, f=0.5)
    brake = P.parse_brake("A", 0.10, "wait30", "counts")
    res = run(
        panel, p, COSTS, DB.dip_signal(panel, 0.5), brake=brake, brake_signal=P.index_signal(panel, 0.5)
    )
    stop, back = res.attrs["stops"].tolist(), res.attrs["buybacks"].tolist()
    assert stop == [11] and back == [41]
    asked = res.attrs["asked"].tolist()
    assert set(range(11, 42)).isdisjoint(asked) and set(range(11)) | set(range(42, n)) == set(asked)
    first, second = res.attrs["ladders"]
    assert first["dropped"] == 41 and all(cl is None or cl < 11 for cl in first["crossed"])
    assert (
        first["crossed"][:4] == [7, 8, 9, 10] and first["crossed"][4] is None
    )  # I fell through it while stopped
    assert second["start"] == 42 and second["high"] == res.attrs["ladders"][1]["high"]
    v = P.wallet_values(res["ret"].to_numpy(), D)
    w = res[list(pf.WEIGHT_COLUMNS)].to_numpy()
    assert second["base"] == pytest.approx(v[42] * (1.0 - w[42].sum()), rel=1e-12)
    reasons = list(res.attrs["reasons"])
    assert reasons[:7] == ["first", "buy", "buy", "buy", "buy", "stop", "buyback"] and reasons[7] == "buy"
    DB.check_values(res)
    P.check_book(res, panel, COSTS)
    assert res.attrs["bought_back"].tolist() == [41]


def test_a_step_whose_book_parts_from_the_engine_is_a_consistency_error(monkeypatch):
    real = DB._Book.advance

    def off(self, target):
        real(self, target)
        if self.t == 5:
            self.w = [self.w[0] * (1.0 + 1e-15), self.w[1]]

    monkeypatch.setattr(DB._Book, "advance", off)
    panel = random_panel(30, 3)
    with pytest.raises(DB.ConsistencyError, match="close 5: the engine's weights"):
        run(panel, params("hold", s0=0.3))


def test_an_order_that_fails_check_targets_is_a_consistency_error(monkeypatch):
    monkeypatch.setattr(DB, "_cap", lambda w, amount, f, mn, mc: amount)
    panel, sig, p = _big_buy(0.0, 0.5)
    with pytest.raises(DB.ConsistencyError, match="close 2: the order's targets fail check_targets"):
        run(panel, p, signal=sig)


# ------------------------------------------------------------------------------------------------ the checks fire


def _dip_and_signal():
    panel = random_panel(300, 21, (0.07, 0.08))
    sig = DB.dip_signal(panel, 0.5)
    return panel, sig, run(panel, params(setting=(0.1, 0.05, 0.1, 1.0)), COSTS, sig)


def test_check_events_fires_on_a_moved_trigger_crossing_or_re_arm():
    panel, sig, res = _dip_and_signal()
    DB.check_events(res, sig)
    assert res.attrs["ladders"] and res.attrs["ladders"][0]["rearm"] is not None
    for change in ("start", "crossed", "rearm"):
        bad = res.copy()
        bad.attrs = {**res.attrs, "ladders": [dict(lad) for lad in res.attrs["ladders"]]}
        lad = bad.attrs["ladders"][0]
        if change == "crossed":
            lad["crossed"] = [lad["crossed"][0] + 1, *lad["crossed"][1:]]
        else:
            lad[change] = lad[change] + 1
        with pytest.raises(DB.ConsistencyError, match="differ from the one-pass recompute"):
            DB.check_events(bad, sig)


def test_check_order_targets_and_check_twin_and_check_values_fire():
    panel, sig, res = _dip_and_signal()
    DB.check_order_targets(res, LIM)
    for change, msg in (
        ({"order_targets": res.attrs["order_targets"] * 1.5}, "fails check_targets"),
        (
            {"reasons": np.asarray(["first", *list(res.attrs["reasons"])[1:]], dtype=object)},
            "first buy is the close-0",
        ),
        ({"reasons": np.asarray(list(res.attrs["reasons"])[1:], dtype=object)}, "not aligned"),
        ({"reasons": np.asarray(["sell"] * len(res.attrs["reasons"]), dtype=object)}, "not aligned"),
    ):
        bad = res.copy()
        bad.attrs = {**res.attrs, **change}
        with pytest.raises(DB.ConsistencyError, match=msg):
            DB.check_order_targets(bad, LIM)
    hold = run(panel, params("hold"), COSTS)
    twin = run(panel, params("dca", total=900.0), COSTS)
    DB.check_twin(twin, 900.0, hold)
    with pytest.raises(DB.ConsistencyError, match="is not its dip run's"):
        DB.check_twin(twin, 900.0 * (1 + 1e-11), hold)
    zero = run(panel, params("dca", total=0.0), COSTS)
    other = run(panel, params("hold", s0=0.3), COSTS)
    with pytest.raises(DB.ConsistencyError, match="differs from hold in"):
        DB.check_twin(zero, 0.0, other)
    same_cols = zero.copy()
    same_cols.attrs = {**zero.attrs, "orders": np.asarray([3], dtype=np.int64)}
    with pytest.raises(DB.ConsistencyError, match="in its orders or fills"):
        DB.check_twin(same_cols, 0.0, hold)
    DB.check_values(res)
    bad = res.copy()
    moved = res.attrs["book_values"].copy()
    moved[100] *= 1.0 + 1e-11
    bad.attrs = {**res.attrs, "book_values": moved}
    with pytest.raises(DB.ConsistencyError, match="book values differ"):
        DB.check_values(bad)


# ------------------------------------------------------------------------------------------------ measures


def test_the_measures_by_hand_on_a_hand_built_run():
    """Two ladders on flat prices at zero cost: every measure of section 8 by hand, and the knife."""
    n = 40
    idx = days(n)
    i = [1.0] * 3 + [0.85] * 3 + [0.75] * 4 + [0.6] * 5 + [1.0] * 5 + [0.8] * 20
    hi = [1.0] * n
    sig = hand_signal(idx, i, hi)
    p = params(setting=(0.10, 0.10, 0.25, 0.50), s0=0.0, f=0.5)
    res = run(flat(n), p, signal=sig)
    m = DB.run_measures(res, ZERO, sig)
    # ladder 0: trigger 3 (piece 1: 1250), close 6 (I 0.75 under 0.81: piece 2: 1250), re-arm at 15
    # ladder 1: trigger 20 on the cash left (2500): 0.8 is under 0.9 and 0.81: two pieces of 625
    assert [lad["start"] for lad in res.attrs["ladders"]] == [3, 20]
    assert res.attrs["orders"].tolist() == [3, 6, 20]
    assert m["ladders"] == 2 and m["ladders_filled"] == 2 and m["orders"] == 3 and m["pieces"] == 4
    assert m["ordered_usd"] == m["sent_usd"] == 1250.0 + 1250.0 + 1250.0 and m["capped_usd"] == 0.0
    assert m["delta"] == 3750.0 / D and m["first_order_days"] == 3.0 and m["limit_fixes"] == 0
    assert m["usdc_left"] == pytest.approx(1250.0 / D, rel=1e-12) and m["F"] == 0.0 and m["v_end"] == D
    rows = DB.ladder_rows(res, sig)
    assert [r["knife"] for r in rows] == [1.0 - 0.6 / 0.75, 1.0 - 0.8 / 0.8]  # from the fill open to the low
    assert [(r["first_order"], r["last_order"], r["rearm"]) for r in rows] == [(3, 6, 15), (20, 20, -1)]
    assert m["knife_worst"] == 1.0 - 0.6 / 0.75
    assert math.isnan(DB.run_measures(res, ZERO)["knife_worst"])  # without the signal
    assert math.isnan(DB.ladder_rows(res, None)[0]["knife"])


def test_the_knife_runs_through_the_re_arm_close_when_the_order_fills_on_it():
    n = 10
    idx = days(n)
    i = [1.0, 1.0, 0.85, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    sig = hand_signal(idx, i, [1.0] * n)
    res = run(flat(n), params(setting=(0.10, 0.10, 0.25, 0.25)), signal=sig)
    (row,) = DB.ladder_rows(res, sig)
    assert (row["last_order"], row["rearm"]) == (2, 3) and row["knife"] == 1.0 - 1.0 / 0.85


def test_the_knife_runs_from_the_fill_row_s_open_not_a_close():
    """Section 8: the knife falls from I at the open of the last order's fill row u. Here that open (0.75) is neither
    the order close's I (0.70) nor row u's own close (0.72), as on real bars whose opens gap (#74)."""
    n = 10
    idx = days(n)
    i = [1.0, 1.0, 0.85, 0.85, 0.7, 0.72, 0.71, 1.0, 1.0, 1.0]
    sig = hand_signal(idx, i, [1.0] * n)
    sig.iloc[5, sig.columns.get_loc("I_open")] = 0.75
    res = run(flat(n), params(setting=(0.10, 0.10, 0.25, 0.50)), signal=sig)
    assert res.attrs["orders"].tolist() == [2, 4]  # line 1 (0.9) at the trigger, line 2 (0.81) at close 4
    (row,) = DB.ladder_rows(res, sig)
    assert (row["last_order"], row["rearm"]) == (4, 7)
    assert row["knife"] == 1.0 - 0.71 / 0.75  # the low of closes 5 .. 7 over the open of row 5
    assert DB.run_measures(res, ZERO, sig)["knife_worst"] == 1.0 - 0.71 / 0.75


def test_delta_is_over_b0_not_the_first_ladder_s_base():
    """Section 8: delta = ordered / B_0 with B_0 = (1 - s0) D. With s0 = 0.30 and costs on, the first buy's costs and
    the price moves leave the first ladder's base B away from B_0 (#74)."""
    n = 8
    idx = days(n)
    sig = hand_signal(idx, [1.0, 1.0, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85], [1.0] * n)
    p = params(setting=(0.10, 0.10, 0.10, 0.25), s0=0.30, f=0.5)
    res = run(panel_on(idx, path(n, r1=110.0), path(n, r1=95.0)), p, costs=COSTS, signal=sig)
    m = DB.run_measures(res, COSTS, sig)
    base = res.attrs["ladders"][0]["base"]
    assert res.attrs["ladders"][0]["start"] == 2 and base != 0.7 * D
    assert m["ordered_usd"] > 0.0
    assert m["delta"] == m["ordered_usd"] / (0.7 * D) and m["delta"] != m["ordered_usd"] / base


def test_a_ladder_capped_to_nothing_is_not_filled():
    """Section 8's 'orders and pieces filled': a ladder whose one crossed piece is capped to nothing (the first buy
    leaves cash at exactly 22%) is a ladder started but not filled, with no piece filled (#74)."""
    n = 6
    idx = days(n)
    sig = hand_signal(idx, [1.0] * n, [1.2] * n)
    res = run(flat(n), params(s0=0.78, f=0.5, setting=(0.10, 0.10, 0.10, 0.25)), signal=sig)
    (b,) = buys(res)
    assert (b["close"], b["lines"], b["sent"]) == (0, 1, 0.0) and b["capped"] > 0.0
    m = DB.run_measures(res, ZERO, sig)
    assert m["ladders"] == 1 and m["ladders_filled"] == 0 and m["pieces"] == 0 and m["orders"] == 0
    assert math.isnan(m["first_order_days"]) and m["capped_usd"] == m["ordered_usd"] > 0.0


def test_the_first_order_day_and_the_usdc_left_by_hand():
    """The trigger at close 0 is capped to nothing (cash at 22%); prices fall 20%, so line 2 is sent at close 2; the
    last row moves the price. The first order is 2 days from close 0 (not the trigger's 0), one ladder and one piece
    are filled, and the USDC left is read at the last close (#74)."""
    n = 6
    idx = days(n)
    sig = hand_signal(idx, [1.0, 1.0, 0.9, 0.9, 0.9, 0.9], [1.2] * n)
    prices = path(n, r2=80.0, r5=90.0)
    p = params(s0=0.78, f=0.5, setting=(0.10, 0.10, 0.10, 0.25))
    res = run(panel_on(idx, prices, prices), p, signal=sig)
    assert res.attrs["orders"].tolist() == [0, 2] and list(res.attrs["reasons"]) == ["first", "buy"]
    m = DB.run_measures(res, ZERO, sig)
    assert m["first_order_days"] == 2.0 and m["ladders_filled"] == 1 and m["pieces"] == 1 and m["orders"] == 1
    units = 19.5 + 55.0 / 80.0  # 1950 USD at 100, then 55 USD at the open of row 3 (80) per coin
    assert m["usdc_left"] == pytest.approx(990.0 / (990.0 + 2 * units * 90.0), rel=1e-12)


def test_compare_twins_by_hand():
    dip = {"v_end": 5500.0, "ordered_usd": 1000.0}
    got = DB.compare_twins(dip, {"v_end": 5000.0}, {"v_end": 6000.0}, {"v_end": 5500.0})
    assert got == {"T_dca": 5500.0 / 5000.0 - 1.0, "T_lump": 5500.0 / 6000.0 - 1.0, "T_hold": 0.0, "G": 0.5}
    assert math.isnan(DB.compare_twins({**dip, "ordered_usd": 0.0}, *[{"v_end": 1.0}] * 3)["G"])


# ------------------------------------------------------------------------------------------------ the rules


def make_pool(
    settings=((0.1, 0.1, 0.1, 0.25),),
    starts=((0.0, 0.5),),
    windows=range(49),
    *,
    F=0.3,
    F_dca=0.3,
    orders=1,
    G=0.0,
    delta=0.5,
    source="KRAKEN",
    cost="1x",
) -> pd.DataFrame:
    """A runs table by hand: every value a scalar or a callable (setting, start, window) -> value."""

    def at(v, s, st_, w):
        return v(s, st_, w) if callable(v) else v

    rows = []
    for s in settings:
        for st_ in starts:
            for w in windows:
                keys = {
                    "source": source,
                    "cost": cost,
                    "Y": s[0],
                    "Z": s[1],
                    "X": s[2],
                    "M": s[3],
                    "s0": st_[0],
                    "f": st_[1],
                }
                common = {**keys, "window": w, "status": "ok", "year": 2017 + w // 12}
                rid = f"{s}:{st_}:{w}"
                rows.append(
                    {
                        **common,
                        "run_id": f"dip:{rid}",
                        "kind": "dip",
                        "F": at(F, s, st_, w),
                        "orders": at(orders, s, st_, w),
                        "G": at(G, s, st_, w),
                        "delta": at(delta, s, st_, w),
                        "T_dca": 0.01 * (w - 20),
                        "T_lump": -0.01 * w,
                        "T_hold": 0.02,
                        "usdc_left": 0.4,
                        "knife_worst": 0.1,
                        "ladders": 1,
                        "fees_pct_per_year": 0.1,
                    }
                )
                for kind in ("dca", "lump"):
                    rows.append(
                        {**common, "run_id": f"{kind}:{rid}", "kind": kind, "F": at(F_dca, s, st_, w)}
                    )
    for st_ in starts:
        for w in windows:
            rows.append(
                {
                    "source": source,
                    "cost": cost,
                    **dict.fromkeys(("Y", "Z", "X", "M"), math.nan),
                    "s0": st_[0],
                    "f": st_[1],
                    "window": w,
                    "status": "ok",
                    "year": 2017 + w // 12,
                    "run_id": f"hold:{st_}:{w}",
                    "kind": "hold",
                    "F": 0.2,
                }
            )
    return pd.DataFrame(rows)


def test_d1_active_needs_at_least_half_of_the_windows():
    for active, default in ((25, (0.1, 0.1, 0.1, 0.25)), (24, DB.NO_DEFAULT)):
        pool = make_pool(orders=lambda s, st_, w, a=active: 1 if w < a else 0)
        d = DB.d1(pool)
        assert d["default"] == default and d["table"][0]["active_windows"] == active
    pool41 = make_pool(windows=range(8, 49), orders=lambda s, st_, w: 1 if w < 29 else 0)  # 21 of 41
    assert DB.d1(pool41)["default"] != DB.NO_DEFAULT and DB.d1(pool41)["windows"] == 41
    pool41 = make_pool(windows=range(8, 49), orders=lambda s, st_, w: 1 if w < 28 else 0)  # 20 of 41
    assert DB.d1(pool41)["default"] == DB.NO_DEFAULT
    # an even count (a boom removal can leave one): exactly half is active
    for active, usable in ((24, True), (23, False)):
        pool48 = make_pool(windows=range(1, 49), orders=lambda s, st_, w, a=active: 1 if w <= a else 0)
        d = DB.d1(pool48)
        assert d["windows"] == 48 and d["table"][0]["active_windows"] == active
        assert d["table"][0]["active"] is usable and (d["default"] != DB.NO_DEFAULT) is usable


def test_d1_q_equal_to_q_dca_passes_and_one_ulp_more_fails():
    x = 0.37
    assert DB.d1(make_pool(F=x, F_dca=x))["table"][0]["Q_pass"]
    d = DB.d1(make_pool(F=nxt(x, 1.0), F_dca=x))
    assert not d["table"][0]["Q_pass"] and d["default"] == DB.NO_DEFAULT

    # a percentile between two values: Q exactly Q_dca with different arrays
    def ff(s, st_, w):
        return 0.1 if w < 44 else 0.5

    pool = make_pool(
        F=ff, F_dca=lambda s, st_, w: float(np.percentile([ff(s, st_, k) for k in range(49)], 90))
    )
    assert DB.d1(pool)["table"][0]["Q"] == DB.d1(pool)["table"][0]["Q_dca"]


def test_d1_the_worst_f_guard_at_equality():
    def dip_f(s, st_, w):
        return 0.6 if w == 0 else 0.1

    assert DB.d1(make_pool(F=dip_f, F_dca=lambda s, st_, w: 0.6 if w == 1 else 0.2))["table"][0]["worst_pass"]
    d = DB.d1(make_pool(F=dip_f, F_dca=lambda s, st_, w: nxt(0.6, 0.0) if w == 1 else 0.2))
    assert d["table"][0]["Q_pass"] and not d["table"][0]["worst_pass"] and d["default"] == DB.NO_DEFAULT


def test_d1_one_failing_start_makes_a_setting_unusable():
    starts = ((0.0, 0.5), (0.3, 0.75))
    pool = make_pool(starts=starts, F=lambda s, st_, w: 0.4 if st_ == (0.3, 0.75) else 0.3, F_dca=0.3)
    d = DB.d1(pool)
    assert [r["pass"] for r in d["table"]] == [True, False] and d["default"] == DB.NO_DEFAULT
    assert d["settings"][0]["usable"] is False


def test_d1_ranks_by_g_then_delta_then_y_z_x_and_the_smaller_m():
    a, b = (0.1, 0.1, 0.1, 0.25), (0.2, 0.05, 0.1, 0.5)
    g = {a: 0.010, b: 0.020}
    pool = make_pool(settings=(a, b), G=lambda s, st_, w: g[s])
    assert DB.d1(pool)["default"] == b
    # G within 1e-12: delta decides (exactly), even against the larger G
    g = {a: 0.020, b: 0.020 - 1e-12}
    pool = make_pool(
        settings=(a, b), G=lambda s, st_, w: g[s], delta=lambda s, st_, w: 0.6 if s == a else 0.5
    )
    d = DB.d1(pool)
    assert d["default"] == a and sorted(d["candidates"]) == [a, b]
    g = {a: 0.020, b: 0.020 - 2e-12}  # outside the tie: b is not a candidate
    pool = make_pool(
        settings=(a, b), G=lambda s, st_, w: g[s], delta=lambda s, st_, w: 0.5 if s == a else 0.9
    )
    assert DB.d1(pool)["default"] == a and DB.d1(pool)["candidates"] == [a]
    # everything equal: the larger Y, then Z, then X, then the smaller M
    for pair, want in (
        (((0.1, 0.2, 0.25, 0.25), (0.2, 0.05, 0.1, 1.0)), (0.2, 0.05, 0.1, 1.0)),
        (((0.2, 0.1, 0.25, 0.25), (0.2, 0.2, 0.1, 1.0)), (0.2, 0.2, 0.1, 1.0)),
        (((0.2, 0.2, 0.1, 0.25), (0.2, 0.2, 0.25, 1.0)), (0.2, 0.2, 0.25, 1.0)),
        (((0.2, 0.2, 0.25, 0.5), (0.2, 0.2, 0.25, 0.25)), (0.2, 0.2, 0.25, 0.25)),
    ):
        assert DB.d1(make_pool(settings=pair))["default"] == want


def test_d1_a_g_tie_of_exactly_1e_12_is_a_tie_and_one_ulp_more_is_not():
    """Section 9 rule 4: candidates are 'within 1e-12' of the largest G~, the boundary included (#74)."""
    a, b = (0.1, 0.1, 0.1, 0.25), (0.2, 0.05, 0.1, 0.5)
    assert abs(0.0 - 1e-12) == 1e-12
    pool = make_pool(
        settings=(a, b),
        G=lambda s, st_, w: 1e-12 if s == a else 0.0,
        delta=lambda s, st_, w: 0.5 if s == a else 0.9,
    )
    d = DB.d1(pool)
    assert sorted(d["candidates"]) == [a, b] and d["default"] == b  # delta decides
    up = nxt(1e-12, 1.0)
    pool = make_pool(
        settings=(a, b),
        G=lambda s, st_, w: up if s == a else 0.0,
        delta=lambda s, st_, w: 0.5 if s == a else 0.9,
    )
    d = DB.d1(pool)
    assert d["candidates"] == [a] and d["default"] == a


def test_d1_leaves_runs_without_an_order_out_of_g():
    def g(s, st_, w):
        return 100.0 if w >= 30 else 0.01

    pool = make_pool(
        orders=lambda s, st_, w: 0 if w >= 30 else 1, G=g, delta=lambda s, st_, w: 0.0 if w >= 30 else 0.8
    )
    got = DB.d1(pool)["settings"][0]
    assert got["G_med"] == 0.01 and got["runs_with_order"] == 30
    assert got["delta_med"] == 0.8  # delta's median is over every run of the setting: 30 of 49 at 0.8
    pool = make_pool(
        orders=lambda s, st_, w: 0 if w >= 20 else 1, delta=lambda s, st_, w: 0.0 if w >= 20 else 0.8
    )
    assert (
        DB.d1(pool)["settings"][0]["delta_med"] == 0.0
    )  # 29 of 49 at 0: never the median of the runs with an order


def test_d1_missing_flows_through():
    pool = make_pool()
    bad = pool.copy()
    bad.loc[bad.index[5], "status"] = "failed"
    assert DB.d1(bad)["default"] == DB.MISSING and "failed" in DB.d1(bad)["reason"]
    hold_fail = pool.copy()
    hold_fail.loc[hold_fail["kind"] == "hold", "status"] = "failed"
    assert DB.d1(hold_fail)["default"] == DB.MISSING
    assert DB.d1(pool[pool["kind"] != "dca"])["default"] == DB.MISSING
    nan_g = make_pool(G=math.nan)
    d = DB.d1(nan_g)
    assert d["default"] == DB.MISSING and "not finite" in d["reason"]
    with pytest.raises(ValueError, match="one run per window"):
        DB.d1(pool.drop(index=pool.index[0]))


def test_d2_labels_and_their_order():
    head = {"default": (0.1, 0.1, 0.1, 0.25)}
    same, other, none = (
        {"default": (0.1, 0.1, 0.1, 0.25)},
        {"default": (0.2, 0.1, 0.1, 0.25)},
        {"default": DB.NO_DEFAULT},
    )
    missing = {"default": DB.MISSING}
    assert DB.d2(head, {"a": same, "b": same})["label"] == DB.ROBUST
    assert DB.d2(head, {"a": same, "b": other, "c": None})["label"] == "NOT ROBUST (b, c: MISSING)"
    assert DB.d2(head, {"a": none, "b": missing})["label"] == "NOT ROBUST (a, b: MISSING)"
    assert DB.d2(head, {"a": same, "b": missing})["label"] == "MISSING (b)"
    assert DB.d2(head, {"a": None})["label"] == "MISSING (a)"
    assert DB.d2({"default": DB.NO_DEFAULT}, {"a": none})["label"] == DB.ROBUST
    assert DB.d2({"default": DB.NO_DEFAULT}, {"a": same})["label"] == "NOT ROBUST (a)"
    assert DB.d2({"default": DB.MISSING}, {"a": same})["label"] == "MISSING (headline)"
    got = DB.d2(head, {"a": same, "b": other})
    assert got["checks"] == {"a": (0.1, 0.1, 0.1, 0.25), "b": (0.2, 0.1, 0.1, 0.25)} and got["moved"] == ["b"]


def test_the_boom_windows_by_hand_against_the_calendar():
    """protect's 24-month rule (section 9, D2): window k (months M_k .. M_(k+23)) overlaps year Y when
    12 (Y - 2017) - 23 <= k <= 12 (Y - 2017) + 11; without 2017 37 windows stay, without 2017 and 2020 two."""
    month0 = pd.Timestamp("2017-01-01", tz="UTC")
    for k in range(49):
        months = {(month0 + pd.DateOffset(months=k + j)).year for j in range(24)}
        for year in range(2017, 2023):
            assert P.overlaps(k, year) == (year in months)
    assert P.windows_without(range(49), [2017]) == list(range(12, 49))
    assert P.windows_without(range(49), [2017, 2020]) == [12, 48]
    assert P.windows_without(range(8, 49), [2021]) == list(range(8, 25))
    removals = P.boom_removals({2017: 9.0, 2018: -0.7, 2019: 0.9, 2020: 3.0, 2021: 0.6, 2022: -0.6})
    assert [r["years"] for r in removals] == [[2017], [2017, 2020]]


def test_d3_by_hand():
    s = (0.1, 0.1, 0.1, 0.25)
    pool = make_pool(
        settings=(s,), windows=range(24), F=lambda a, b, w: 0.01 * w, F_dca=0.2, G=lambda a, b, w: w - 10.0
    )
    ladders = pd.DataFrame(
        {"run_id": [f"dip:{s}:(0.0, 0.5):{w}" for w in range(24)], "knife": [0.01 * w for w in range(24)]}
    )
    got = DB.d3(pool, ladders, s, 0.35)
    (row,) = got["per_start"]
    g = np.arange(24) - 10.0
    assert row["G"] == {
        "n": 24,
        "p10": float(np.percentile(g, 10)),
        "median": float(np.median(g)),
        "p90": float(np.percentile(g, 90)),
        "share_above_0": 13 / 24,
    }
    assert row["T_dca"]["share_above_0"] == 3 / 24 and row["T_hold"]["share_above_0"] == 1.0
    assert (
        row["Q"] == float(np.percentile(0.01 * np.arange(24), 90))
        and row["Q_dca"] == 0.2
        and row["Q_hold"] == 0.2
    )
    assert row["above_budget"] == {"Q": False, "Q_dca": False, "Q_lump": False, "Q_hold": False}
    assert row["knife_median"] == float(np.median(0.01 * np.arange(24))) and row["knife_worst"] == 0.23
    assert sorted(row["by_year"]) == [2017, 2018] and row["by_year"][2018]["G"]["n"] == 12
    assert row["by_year"][2017]["G"]["median"] == float(np.median(np.arange(12) - 10.0))
    assert got["budget"] == 0.35 and got["knife_worst"] == 0.23
    assert DB.d3(pool, ladders, s, None)["budget"] == DB.MISSING
    assert DB.d3(pool, ladders, s, None)["per_start"][0]["above_budget"] is None
    assert DB.d3(pool, ladders, DB.NO_DEFAULT, 0.35) == {"status": DB.NO_DEFAULT}
    bad = pool.copy()
    bad.loc[bad.index[0], "status"] = "failed"
    assert DB.d3(bad, ladders, s, 0.35)["status"] == DB.MISSING
    no_orders = make_pool(settings=(s,), windows=range(3), orders=0)
    empty = DB.d3(no_orders, ladders.iloc[:0], s, 0.35)["per_start"][0]
    assert empty["G"]["n"] == 0 and empty["knife_median"] is None and empty["knife_worst"] is None


def test_the_setting_table_by_hand():
    s = (0.1, 0.1, 0.1, 0.25)
    pool = make_pool(
        settings=(s,), windows=range(5), G=lambda a, b, w: float(w), orders=lambda a, b, w: int(w > 0)
    )
    (row,) = DB.setting_table(pool)
    assert row["runs"] == 5 and row["failed"] == 0 and row["active_share"] == 0.8
    assert row["G_med"] == 2.5 and row["T_dca_med"] == float(np.median(0.01 * (np.arange(5) - 20)))
    pool.loc[(pool["kind"] == "dip"), "status"] = "failed"
    (row,) = DB.setting_table(pool)
    assert row["failed"] == 5 and "G_med" not in row
    none = make_pool(settings=(s,), windows=range(2), orders=0)
    none["knife_worst"] = math.nan
    (row,) = DB.setting_table(none)
    assert row["G_med"] is None and row["knife_worst"] is None
