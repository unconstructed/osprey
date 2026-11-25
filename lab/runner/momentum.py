"""momentum-bold: each Monday hold the top K coins of a volume-ranked universe by trailing return, the rest in USDC.

**Scouting only; never in reports** (AGENTS.md hard rule 3), like :mod:`lab.runner.portfolio`, whose execution model
this generalises to many coins. The rule, the universe, the delisting haircut and the gates are pinned in
``research/momentum-bold/PLAN.md``; section numbers below are that plan's.

The wide panel (pinned format)
------------------------------
A DataFrame indexed by ``ts`` (UTC bar CLOSE times at 00:00, microsecond unit, every step exactly one day) with a
2-level column MultiIndex ``("symbol", "field")``: Binance USDT symbols (``"BTCUSDT"``) in ascending order, each
with exactly :data:`FIELDS`. A symbol's row is either all NaN (no bar that day: missing days stay missing) or all
finite with positive prices, ``low <= open, close <= high`` and non-negative volumes. ``BTCUSDT`` must be present.
``attrs["snapshot_id"]`` is a non-empty string. :func:`make_wide_panel` builds it; :func:`validate_wide` checks it.
Rows are days, so a lookback of L rows is L days. ``lab.search`` slices it with ``iloc`` unchanged.

Execution (section 5)
---------------------
A decision at close t (a schedule row) fills at the OPEN of t+1; the decision at the last close is never filled.
The book holds coin units and USDC cash. At a fill: V_open = cash + sum units x open; each coin's drifted weight is
units x open / V_open, its leg is |target - drifted| x V_open in USD and costs ``usd x rate(usd) + gas`` (the
minor-coin rate for coins other than BTC and ETH, :class:`CoinCosts`); V_after = V_open - legs' costs; then units =
target x V_after / open and cash = (1 - sum targets) x V_after (portfolio.py's pro-rata re-cut). A coin targeted
but without a bar at the fill row is not bought (its share stays cash). **Delisting (section 6):** a held coin with
no bar at row t is sold at row t at its last close x (1 - :data:`HAIRCUT`), paying its leg cost (capped at the
proceeds), before any fill on that row. Turnover and cost are fractions of V_ref, the book's value just before the
row's trades (held coins at the open, a force-sold coin at its last close); the haircut counts as cost.

Result: ``ret``, ``position`` (coin share at the close), ``turnover``, ``cost``, ``n_held``; ``attrs``:
``trade_returns`` (one per fill row, V_ref to the next fill row's V_ref, the last to the final value),
``n_trades``, ``fills`` (one row per leg), ``orders`` (schedule rows sent), ``forced`` (force-sold legs),
``snapshot_id``. It passes :func:`lab.runner.interface.validate_result` with the panel's BTC bars.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from lab.config import CONFIG_DIR
from lab.runner.portfolio import _budget
from lab.runner.reference import Costs, _check_params, _param_int

FIELDS = ("open", "high", "low", "close", "volume", "quote_volume")
QUOTE = "USDT"
BTC = "BTCUSDT"
MAJORS = frozenset({"BTCUSDT", "ETHUSDT"})
TOP_N = 20  # section 3: the universe
VOLUME_DAYS = 30
MIN_HISTORY = 91  # a coin's first bar at least this many rows before the decision row
SMA_DAYS = 200
WEEKDAY = 0  # Monday 00:00 UTC closes (the bar of Sunday), as trend.py
HAIRCUT = 0.30  # section 6
FILTERS = ("none", "btc_sma200", "abs_mom")
LOOKBACKS = (14, 28, 56, 91)
KS = (3, 5, 10)
WARMUP = 200  # rows before each test block: every window of the rule is full at the block's first row
WEIGHT_SUM_TOL = 1e-12
PLATEAU_FACTORS = (0.8, 1.2)
PLATEAU_KEEP = 0.7
GATE_NAMES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")
E1_P = 0.05

# Section 3's exclusion list (by base asset, the symbol without "USDT").
STABLECOINS = frozenset({
    "USDC", "BUSD", "TUSD", "USDP", "PAX", "USDS", "USDSB", "DAI", "FDUSD", "SUSD", "UST", "USTC", "GUSD", "USDD",
    "PYUSD", "EURI", "AEUR", "USDJ", "FRAX", "LUSD", "USDE", "USD1", "BFUSD", "XUSD",
})
FIAT = frozenset({"EUR", "GBP", "AUD", "JPY", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "IDRT", "BIDR", "BVND", "BKRW", "ARS", "PLN", "RON", "MXN", "COP", "CZK"})
WRAPPED_PEGGED = frozenset({"WBTC", "WBETH", "BETH", "STETH", "RENBTC", "PAXG", "XAUT", "BTCB", "WETH", "CBETH", "RETH"})
LEVERAGED_UNDERLYINGS = frozenset({
    "BTC", "ETH", "BNB", "ADA", "LINK", "DOT", "XRP", "LTC", "TRX", "EOS", "XTZ", "YFI", "SXP", "FIL", "UNI", "SUSHI",
    "AAVE", "BCH", "XLM", "1INCH",
})
_LEVERAGED_RE = re.compile(r"^(?P<under>[A-Z0-9]+?)(?P<kind>UP|DOWN)$")
_BULL_BEAR_RE = re.compile(r"^[A-Z0-9]*(BULL|BEAR)$")

Schedule = Mapping[int, Mapping[str, float]]


# ------------------------------------------------------------------------------------------------ symbols


def base_of(symbol: str) -> str:
    """The base asset of a Binance USDT symbol ("BTCUSDT" -> "BTC"); ``ValueError`` for anything else."""
    if not isinstance(symbol, str) or not symbol.endswith(QUOTE) or len(symbol) <= len(QUOTE):
        raise ValueError(f"not a Binance USDT symbol: {symbol!r}")
    return symbol[: -len(QUOTE)]


def exclusion(symbol: str) -> str | None:
    """Why a symbol never enters the universe (section 3), or None. BTC and ETH are never excluded."""
    base = base_of(symbol)
    if base in STABLECOINS:
        return "stablecoin"
    if base in FIAT:
        return "fiat"
    if base in WRAPPED_PEGGED:
        return "wrapped or pegged"
    m = _LEVERAGED_RE.match(base)
    if (m and m["under"] in LEVERAGED_UNDERLYINGS) or _BULL_BEAR_RE.match(base):
        return "leveraged token"
    return None


# ------------------------------------------------------------------------------------------------ the panel


def validate_wide(bars: pd.DataFrame) -> None:
    """Raise ``ValueError`` unless ``bars`` is a wide panel in the pinned format (module docstring)."""
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("wide panel must be a pandas DataFrame")
    cols = bars.columns
    if not isinstance(cols, pd.MultiIndex) or list(cols.names) != ["symbol", "field"]:
        raise ValueError("wide panel columns must be a MultiIndex named ('symbol', 'field')")
    symbols = list(dict.fromkeys(cols.get_level_values(0)))
    if tuple(cols) != tuple((s, f) for s in symbols for f in FIELDS) or symbols != sorted(symbols):
        raise ValueError(f"wide panel columns must be (symbol, field) with fields {FIELDS}, symbols ascending")
    for s in symbols:
        base_of(s)
    if BTC not in symbols:
        raise ValueError(f"wide panel must hold {BTC}")
    if not (bars.dtypes == np.float64).all():
        raise ValueError("wide panel columns must all be float64")
    idx = bars.index
    if not isinstance(idx, pd.DatetimeIndex) or str(idx.tz) != "UTC" or idx.unit != "us" or idx.name != "ts":
        raise ValueError("wide panel index must be a UTC DatetimeIndex named 'ts' in microseconds")
    if len(idx) < 2:
        raise ValueError("wide panel needs at least 2 rows")
    if (idx != idx.normalize()).any() or (np.diff(idx.asi8) != 86_400_000_000).any():
        raise ValueError("wide panel index must be daily closes at 00:00 UTC, one day apart (missing days are NaN)")
    if not isinstance(bars.attrs.get("snapshot_id"), str) or not bars.attrs["snapshot_id"]:
        raise ValueError("wide panel attrs['snapshot_id'] must be a non-empty string")
    v = bars.to_numpy().reshape(len(idx), len(symbols), len(FIELDS))
    fin = np.isfinite(v)
    if ((fin.any(axis=2)) & ~(fin.all(axis=2))).any():
        raise ValueError("a symbol's row must be all NaN (no bar) or all finite")
    o, h, lo, c, vol, qv = (np.where(fin[:, :, 0], v[:, :, i], 1.0) for i in range(6))
    if (np.minimum(np.minimum(o, h), np.minimum(lo, c)) <= 0).any():
        raise ValueError("wide panel holds non-positive prices")
    if (vol < 0).any() or (qv < 0).any():
        raise ValueError("wide panel holds negative volume")
    if (h < np.maximum(o, c)).any() or (lo > np.minimum(o, c)).any():
        raise ValueError("wide panel violates low <= open, close <= high")


def make_wide_panel(frames: Mapping[str, pd.DataFrame], *, snapshot_id: str) -> pd.DataFrame:
    """The wide panel from one daily frame per symbol (``load_bold_daily``'s output): the daily grid from the
    earliest to the latest close of any symbol, each symbol reindexed onto it (days it lacks are NaN). Each frame
    needs :data:`FIELDS`, a tz-aware UTC index of 00:00 closes, strictly increasing, and no NaN."""
    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("make_wide_panel: frames must be a non-empty mapping of symbol -> bars")
    idxs = {}
    for sym, frame in frames.items():
        base_of(sym)
        missing = [f for f in FIELDS if f not in frame.columns]
        idx = frame.index
        if missing:
            raise ValueError(f"make_wide_panel: {sym} lacks {missing}")
        if not isinstance(idx, pd.DatetimeIndex) or idx.tz is None or len(idx) == 0:
            raise ValueError(f"make_wide_panel: {sym} needs a non-empty tz-aware DatetimeIndex of closes")
        idx = idx.tz_convert("UTC").as_unit("us")
        if not idx.is_monotonic_increasing or idx.has_duplicates or (idx != idx.normalize()).any():
            raise ValueError(f"make_wide_panel: {sym} closes must be strictly increasing and at 00:00 UTC")
        if not np.isfinite(frame.loc[:, list(FIELDS)].to_numpy(dtype=float)).all():
            raise ValueError(f"make_wide_panel: {sym} holds NaN (a missing day is a missing row)")
        idxs[sym] = idx
    first = min(i[0] for i in idxs.values())
    last = max(i[-1] for i in idxs.values())
    grid = pd.date_range(first, last, freq="D", name="ts").as_unit("us")
    symbols = sorted(frames)
    blocks = []
    for sym in symbols:
        f = frames[sym].loc[:, list(FIELDS)].astype(np.float64).copy()
        f.index = idxs[sym]
        blocks.append(f.reindex(grid).to_numpy())
    panel = pd.DataFrame(
        np.concatenate(blocks, axis=1),
        index=pd.DatetimeIndex(grid, name="ts", freq=None),
        columns=pd.MultiIndex.from_tuples([(s, f) for s in symbols for f in FIELDS], names=["symbol", "field"]),
    )
    panel.attrs = {"snapshot_id": snapshot_id}
    validate_wide(panel)
    return panel


@dataclass(frozen=True)
class _Arrays:
    symbols: tuple[str, ...]
    o: np.ndarray
    c: np.ndarray
    qv0: np.ndarray  # quote volume, 0 where no bar
    present: np.ndarray
    last_row: np.ndarray  # last row <= t with a bar, -1 if none
    first_row: np.ndarray  # first row with a bar (n if none)
    allowed: np.ndarray  # not excluded
    mondays: np.ndarray


def _arrays(bars: pd.DataFrame) -> _Arrays:
    validate_wide(bars)
    symbols = tuple(dict.fromkeys(bars.columns.get_level_values(0)))
    n, m = len(bars), len(symbols)
    v = bars.to_numpy().reshape(n, m, len(FIELDS))
    present = np.isfinite(v[:, :, 3])
    rows = np.where(present, np.arange(n)[:, None], -1)
    return _Arrays(
        symbols=symbols,
        o=v[:, :, 0],
        c=v[:, :, 3],
        qv0=np.where(present, v[:, :, 5], 0.0),
        present=present,
        last_row=np.maximum.accumulate(rows, axis=0),
        first_row=np.where(present.any(axis=0), present.argmax(axis=0), n),
        allowed=np.array([exclusion(s) is None for s in symbols]),
        mondays=np.flatnonzero(bars.index.day_of_week == WEEKDAY),
    )


# ------------------------------------------------------------------------------------------------ the rule


def _universe(a: _Arrays, t: int) -> np.ndarray:
    """Section 3: column indices of the top :data:`TOP_N` eligible coins at row t by trailing 30-day quote volume
    (rows t-29..t, a missing day counts 0), ties to the symbol first in ascending order. Eligible: not excluded, a
    bar at t, the first bar at row <= t - MIN_HISTORY, and volume > 0."""
    elig = a.allowed & a.present[t] & (a.first_row <= t - MIN_HISTORY)
    vol = a.qv0[max(0, t - VOLUME_DAYS + 1) : t + 1].sum(axis=0)
    cand = np.flatnonzero(elig & (vol > 0.0))
    order = np.lexsort((cand, -vol[cand]))
    return cand[order][:TOP_N]


def _ranked(a: _Arrays, t: int, members: np.ndarray, lookback: int) -> list[tuple[int, float]]:
    """(column, trailing return) for members with a bar at or before row t - lookback, best first, ties to the
    symbol first in ascending order. R = close_t / (the last close at or before row t - lookback) - 1."""
    out = []
    if t - lookback >= 0:
        for j in members.tolist():
            r = a.last_row[t - lookback, j]
            if r >= 0:
                out.append((j, a.c[t, j] / a.c[r, j] - 1.0))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def _risk_on(a: _Arrays, t: int) -> bool:
    """BTC's close at t strictly above the mean of its 200 closes t-199..t (math.fsum); False without them all."""
    b = a.symbols.index(BTC)
    if t < SMA_DAYS - 1 or not a.present[t - SMA_DAYS + 1 : t + 1, b].all():
        return False
    return bool(a.c[t, b] > math.fsum(a.c[t - SMA_DAYS + 1 : t + 1, b].tolist()) / SMA_DAYS)


def parse_params(params, rule: str = "momentum", extra: frozenset = frozenset()) -> tuple[int, int, str]:
    p = _check_params(rule, params, frozenset({"lookback", "k", "filter"}) | extra)
    lookback = _param_int(p, "lookback")
    k = _param_int(p, "k")
    if k > TOP_N:
        raise ValueError(f"{rule}: k must be <= {TOP_N}, got {k!r}")
    filt = p.get("filter")
    if filt not in FILTERS:
        raise ValueError(f"{rule}: filter must be one of {FILTERS}, got {filt!r}")
    return lookback, k, filt


def plan(bars: pd.DataFrame, params, rng: np.random.Generator | None = None) -> dict:
    return _plan(_arrays(bars), params, rng)


def _plan(a: _Arrays, params, rng: np.random.Generator | None) -> dict:
    """The rule's decisions at every Monday row (section 5): ``universe``, ``ranked`` (symbol, R), ``selected``
    and the ``schedule`` (selected coin -> 1/K).

    With ``rng``: the random null (section 8). Each Monday it holds as many coins as the rule selected (n) and keeps
    as many of its previous coins as the rule kept of its own (o, capped by its previous coins still ranked and by
    n), chosen at random among those; the other n - kept coins are drawn at random from the ranked coins it did not
    hold, then (if too few) from its previous coins not kept. Draws are uniform without replacement over ascending
    column order, so the null has the rule's universe, Mondays, cash share and number of swaps."""
    if rng is None:
        lookback, k, filt = parse_params(params)
    else:
        lookback, k, filt = parse_params(params, "random_select", frozenset({"seed"}))
    out: dict = {"universe": {}, "ranked": {}, "selected": {}, "schedule": {}}
    rule_prev: set[int] = set()
    held: set[int] = set()
    for t in a.mondays.tolist():
        members = _universe(a, t)
        ranked = _ranked(a, t, members, lookback)
        sel = [j for j, _ in ranked[:k]]
        if filt == "abs_mom":
            sel = [j for j, r in ranked[:k] if r > 0.0]
        elif filt == "btc_sma200" and not _risk_on(a, t):
            sel = []
        if rng is not None:
            kept_by_rule = len(rule_prev & set(sel))
            rule_prev = set(sel)
            pool = {j for j, _ in ranked}
            stay = sorted(held & pool)
            keep = _draw(rng, stay, min(kept_by_rule, len(stay), len(sel)))
            fresh = _draw(rng, sorted(pool - held), min(len(sel) - len(keep), len(pool - held)))
            rest = _draw(rng, sorted(set(stay) - set(keep)), len(sel) - len(keep) - len(fresh))
            sel = keep + fresh + rest
            held = set(sel)
        out["universe"][t] = tuple(a.symbols[j] for j in members.tolist())
        out["ranked"][t] = tuple((a.symbols[j], r) for j, r in ranked)
        out["selected"][t] = tuple(a.symbols[j] for j in (sel if rng is None else sorted(sel)))
        out["schedule"][t] = {a.symbols[j]: 1.0 / k for j in sorted(sel)}
    return out


def _draw(rng: np.random.Generator, pool: list[int], size: int) -> list[int]:
    return [pool[i] for i in rng.choice(len(pool), size=size, replace=False).tolist()] if size else []


# ------------------------------------------------------------------------------------------------ costs


@dataclass(frozen=True)
class CoinCosts:
    """Per-coin costs (section 7): ``major`` for BTC and ETH, ``minor`` for every other coin (pool fee and slippage
    times ``small_coin_cost_multiplier``, aggregator fee and gas unchanged)."""

    major: Costs
    minor: Costs

    def costs_for(self, symbol: str) -> Costs:
        return self.major if symbol in MAJORS else self.minor

    def leg_cost(self, symbol: str, usd: float) -> float:
        c = self.costs_for(symbol)
        return usd * c.rate(usd) + c.gas_usd_per_trade

    def stressed(self, k: float) -> CoinCosts:
        return CoinCosts(self.major.stressed(k), self.minor.stressed(k))

    @property
    def capital_usd(self) -> float:
        return self.major.capital_usd


def small_coin(costs: Costs, multiplier: float) -> Costs:
    return replace(
        costs,
        pool_fee_bps=costs.pool_fee_bps * multiplier,
        slippage_bps=tuple((size, b * multiplier) for size, b in costs.slippage_bps),
    )


def coin_costs(config_dir: Path | None = None, capital_usd: float = 10_000.0) -> CoinCosts:
    """1x costs from ``config/costs.yaml``; ``small_coin_cost_multiplier`` is required (a number >= 1)."""
    path = Path(config_dir or CONFIG_DIR) / "costs.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    mult = raw.get("small_coin_cost_multiplier")
    if isinstance(mult, bool) or not isinstance(mult, int | float) or not math.isfinite(mult) or mult < 1.0:
        raise ValueError(f"{path}: small_coin_cost_multiplier must be a number >= 1, got {mult!r}")
    major = Costs.from_yaml(path, capital_usd=capital_usd)
    return CoinCosts(major, small_coin(major, float(mult)))


def bold_budget(config_dir: Path | None = None) -> float | None:
    """Bold's ``max_drawdown_budget_pct`` / 100 as read from ``config/risk_levels.yaml`` (None if not a number in
    (0, 100]: MISSING)."""
    raw = yaml.safe_load((Path(config_dir or CONFIG_DIR) / "risk_levels.yaml").read_text()) or {}
    return _budget((raw.get("bold") or {}).get("max_drawdown_budget_pct"))


# ------------------------------------------------------------------------------------------------ the engine


def simulate(bars: pd.DataFrame, costs: CoinCosts, schedule: Schedule) -> pd.DataFrame:
    """Run a schedule (decision row -> {symbol: target weight}) through the book (module docstring)."""
    return _simulate(_arrays(bars), bars, costs, schedule)


def _simulate(a: _Arrays, bars: pd.DataFrame, costs: CoinCosts, schedule: Schedule) -> pd.DataFrame:
    if not isinstance(costs, CoinCosts):
        raise ValueError(f"costs must be a CoinCosts, got {type(costs).__name__}")
    col = {s: j for j, s in enumerate(a.symbols)}
    n = len(bars)
    for t, target in schedule.items():
        ws = list(target.values())
        if (
            not isinstance(t, int | np.integer)
            or not 0 <= t < n
            or any(s not in col for s in target)
            or not all(math.isfinite(w) and w >= 0.0 for w in ws)
            or math.fsum(ws) > 1.0 + WEIGHT_SUM_TOL
        ):
            raise ValueError(f"bad schedule entry at row {t!r}: {dict(target)!r}")
        if any(not a.present[t, col[s]] for s in target):
            raise ValueError(f"schedule row {t}: a target coin has no bar at its decision row")
    ret, pos, turnover, cost, held = (np.zeros(n) for _ in range(5))
    cash, units = costs.capital_usd, {}
    v_prev = cash
    legs, orders, refs = [], [], []
    for t in range(1, n):
        paid = traded = 0.0
        missing = sorted(j for j in units if not a.present[t, j])
        v_ref = cash + math.fsum(
            u * (a.c[a.last_row[t, j], j] if j in missing else a.o[t, j]) for j, u in units.items()
        )
        for j in missing:
            sym = a.symbols[j]
            px = a.c[a.last_row[t, j], j]
            usd = units.pop(j) * px
            gross = usd * (1.0 - HAIRCUT)
            fee = min(costs.leg_cost(sym, gross), gross)
            cash += gross - fee
            paid += usd - gross + fee
            traded += usd
            legs.append((t, sym, "sell", usd, px, usd - gross + fee, True))
        target = schedule.get(t - 1)
        if target is not None:
            orders.append(t - 1)
            v_open = cash + math.fsum(u * a.o[t, j] for j, u in units.items())
            tw = {col[s]: w for s, w in target.items() if w > 0.0 and a.present[t, col[s]]}
            k_usd, new = 0.0, []
            for j in sorted(set(units) | set(tw)):
                drifted = units.get(j, 0.0) * a.o[t, j] / v_open
                usd = abs(tw.get(j, 0.0) - drifted) * v_open
                if usd > 0.0:
                    fee = costs.leg_cost(a.symbols[j], usd)
                    k_usd += fee
                    traded += usd
                    side = "buy" if tw.get(j, 0.0) > drifted else "sell"
                    new.append((t, a.symbols[j], side, usd, a.o[t, j], fee, False))
            if k_usd >= v_open:
                raise ValueError(
                    f"costs of the fill on {bars.index[t]} are {k_usd / v_open:.1%} of a book worth {v_open:.4g} "
                    "USD: it cannot pay them"
                )
            legs += new
            paid += k_usd
            v_after = v_open - k_usd
            units = {j: w * v_after / a.o[t, j] for j, w in tw.items()}
            cash = max(0.0, 1.0 - math.fsum(tw.values())) * v_after
        coins = math.fsum(u * a.c[t, j] for j, u in units.items())
        value = cash + coins
        ret[t] = value / v_prev - 1.0
        pos[t] = coins / value
        held[t] = len(units)
        if traded > 0.0:
            turnover[t], cost[t] = traded / v_ref, paid / v_ref
            refs.append(v_ref)
        v_prev = value
    ends = refs[1:] + [v_prev] if refs else []
    result = pd.DataFrame(
        {"ret": ret, "position": pos, "turnover": turnover, "cost": cost, "n_held": held}, index=bars.index
    )
    fills = pd.DataFrame(legs, columns=["bar", "symbol", "side", "usd", "price", "cost", "forced"]).astype(
        {"bar": np.int64, "symbol": object, "side": object, "usd": float, "price": float, "cost": float, "forced": bool}
    )
    result.attrs = {
        "trade_returns": np.asarray([e / s - 1.0 for s, e in zip(refs, ends, strict=True)], dtype=float),
        "n_trades": len(refs),
        "fills": fills,
        "orders": np.asarray(orders, dtype=np.int64),
        "forced": int(fills["forced"].sum()),
        "snapshot_id": bars.attrs["snapshot_id"],
    }
    return result


def _costs(costs: CoinCosts | None) -> CoinCosts:
    return coin_costs() if costs is None else costs


def momentum(params, bars: pd.DataFrame, costs: CoinCosts | None = None) -> pd.DataFrame:
    """The rule as a ``BacktestFn`` (params ``lookback``, ``k``, ``filter``)."""
    a = _arrays(bars)
    p = _plan(a, params, None)
    res = _simulate(a, bars, _costs(costs), p["schedule"])
    res.attrs["selected"] = p["selected"]
    return res


def random_select(params, bars: pd.DataFrame, costs: CoinCosts | None = None) -> pd.DataFrame:
    """The random-selection null (section 8): the rule's params plus ``seed`` (int >= 0)."""
    _check_params("random_select", params, frozenset({"lookback", "k", "filter", "seed"}))
    seed = _param_int(params, "seed", minimum=0)
    a = _arrays(bars)
    p = _plan(a, params, np.random.default_rng(seed))
    res = _simulate(a, bars, _costs(costs), p["schedule"])
    res.attrs["selected"] = p["selected"]
    return res


def basket(params, bars: pd.DataFrame, costs: CoinCosts | None = None) -> pd.DataFrame:
    """B3 (section 9): each Monday the whole universe at 1 / its size (no params)."""
    _check_params("basket", params, frozenset())
    a = _arrays(bars)
    sched = {}
    for t in a.mondays.tolist():
        u = _universe(a, t)
        sched[t] = {a.symbols[j]: 1.0 / len(u) for j in sorted(u.tolist())}
    return _simulate(a, bars, _costs(costs), sched)


def hold_fixed(params, bars: pd.DataFrame, costs: CoinCosts | None = None) -> pd.DataFrame:
    """B1 and B2 (section 9): ``weights`` ({symbol: w}) bought at row 0 and, with ``every`` (int >= 1), restored at
    rows every, 2 every, ...; ``every`` None holds after the first buy."""
    p = _check_params("hold_fixed", params, frozenset({"weights", "every"}))
    every = None if p.get("every") is None else _param_int(p, "every")
    n = len(bars)
    rows = [0] if every is None else list(range(0, n, every))
    return simulate(bars, _costs(costs), {t: dict(p["weights"]) for t in rows})


# ------------------------------------------------------------------------------------------------ the harness


KEPT_COLUMNS = ("ret", "turnover", "cost", "n_held")


def stitch_frame(
    fn: Callable, per_fold_params: Sequence[Mapping], bars: pd.DataFrame, folds: Sequence, warmup: int = WARMUP
) -> pd.DataFrame:
    """Each fold's params run on ``walk_forward_optimize``'s out-of-sample slice (rows from test[0] - warmup to
    test[-1]), kept from the row after test[0] (:data:`KEPT_COLUMNS`); ``attrs["forced"]`` counts the forced sales
    on kept rows."""
    parts, forced = [], 0
    for params, fold in zip(per_fold_params, folds, strict=True):
        start = max(0, fold.test[0] - warmup)
        res = fn(dict(params), bars.iloc[start : fold.test[-1] + 1])
        fills = res.attrs["fills"]
        forced += int((fills["forced"] & (fills["bar"] > fold.test[0] - start)).sum())
        part = res.loc[bars.index[fold.test[0]] :, list(KEPT_COLUMNS)].iloc[1:]
        part.attrs = {}
        parts.append(part)
    out = pd.concat(parts)
    out.attrs = {"forced": forced}
    return out


def stitch(
    fn: Callable, per_fold_params: Sequence[Mapping], bars: pd.DataFrame, folds: Sequence, warmup: int = WARMUP
) -> pd.Series:
    """:func:`stitch_frame`'s ``ret``: ``walk_forward_optimize``'s ``oos_returns`` exactly, for the same params."""
    s = stitch_frame(fn, per_fold_params, bars, folds, warmup)["ret"]
    s.attrs = {}
    return s


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def plateau_steps(per_fold_params: Sequence[Mapping]) -> list[dict]:
    """Section 10's G5 steps: lookback and k each x0.8 and x1.2 in every fold, rounded half up (k within 1..20)."""
    steps = []
    for name in ("lookback", "k"):
        for factor in PLATEAU_FACTORS:
            folds = []
            for p in per_fold_params:
                q = dict(p)
                q[name] = max(_half_up(p[name] * factor), 1)
                if name == "k":
                    q[name] = min(q[name], TOP_N)
                folds.append(q)
            steps.append({"param": name, "factor": factor, "folds": folds})
    return steps


def _ok(x) -> bool:
    return x is not None and isinstance(x, int | float | np.floating) and math.isfinite(x)


def gate_table(x: Mapping) -> dict[str, str]:
    """Section 10's gates from recorded numbers: PASS, FAIL or MISSING (a missing number never passes).

    Keys of ``x``: ``sharpe``, ``sharpe_2x``, ``dsr_strict``, ``pbo``, ``plateau`` (step Sharpes), ``mc_p5``
    (worst-5% drawdown, negative), ``budget``, ``bench`` ({name: Sharpe}), ``regimes_pass`` (bool or None)."""
    s = x["sharpe"]

    def judge(values, rule) -> str:
        return rule() if all(_ok(v) for v in values) else "MISSING"

    def pf(b: bool) -> str:
        return "PASS" if b else "FAIL"

    bench = list(x["bench"].values())
    return {
        "G1": judge([s], lambda: pf(s >= 1.0)),
        "G2": judge([x["sharpe_2x"]], lambda: pf(x["sharpe_2x"] > 0.5)),
        "G3": judge([x["dsr_strict"]], lambda: pf(x["dsr_strict"] >= 0.95)),
        "G4": judge([x["pbo"]], lambda: pf(x["pbo"] <= 0.25)),
        "G5": judge(
            [s, *x["plateau"]], lambda: pf(s > 0.0 and all(v >= PLATEAU_KEEP * s for v in x["plateau"]))
        ),
        "G6": judge([x["mc_p5"], x["budget"]], lambda: pf(x["mc_p5"] >= -x["budget"])),
        "G7": judge([s, *bench], lambda: pf(len(bench) == 3 and all(s > b for b in bench))),
        "G8": "MISSING" if x["regimes_pass"] is None else pf(bool(x["regimes_pass"])),
    }


def verdict(gates: Mapping[str, str], e1_rank_p) -> dict:
    """CANDIDATE FOR AUDIT only when every gate passes and E1 holds (rank p <= 0.05); else NOT A CANDIDATE."""
    e1 = "MISSING" if not _ok(e1_rank_p) else ("HOLDS" if e1_rank_p <= E1_P else "FAILS")
    failing = [g for g in GATE_NAMES if gates[g] != "PASS"] + ([] if e1 == "HOLDS" else ["E1"])
    return {
        "e1": e1,
        "failing": failing,
        "verdict": "CANDIDATE FOR AUDIT" if not failing else "NOT A CANDIDATE",
    }
