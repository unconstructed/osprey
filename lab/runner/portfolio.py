"""Multi-asset reference rebalancer: hold BTC, ETH and USDC (cash) at target weights, with the DEX cost model.

**Tests, demos and scouting only; never in reports** (AGENTS.md hard rule 3: only Nautilus results count). Same
status as :mod:`lab.runner.reference`, whose execution model and :class:`~lab.runner.reference.Costs` it reuses.

The panel (pinned format, shared with the loader)
-------------------------------------------------
A DataFrame indexed by ``ts`` (UTC bar CLOSE time, microsecond unit, strictly increasing, no duplicates) with a
2-level column MultiIndex named ``("asset", "field")``: assets :data:`ASSETS` = ``("BTC", "ETH")`` in that order
and, per asset, exactly :data:`FIELDS` = ``open, high, low, close, volume`` in that order, all float64, each
asset's block passing :func:`lab.runner.interface.validate_bars`. ``attrs`` holds exactly ``snapshot_id``
(non-empty str), ``instruments`` (``{"BTC": id, "ETH": id}``), ``bar_type`` (a string, or ``{"BTC": ..., "ETH":
...}``) and ``alignment`` (a dict). USDC is cash: price 1, no bars. :func:`validate_panel` enforces all of it.
Rows are bars: ``every`` counts rows, so a close missing from the panel makes one row's return span two bars.

Execution model (copied from ``reference._simulate``, generalised to two coins)
------------------------------------------------------------------------------
- A rule decides at the close of bar t, from data up to and including that close (it sees only the weights at
  that close). The order fills at the OPEN of bar t+1; an order decided at the last close is never filled.
- An order is always the full target vector (w_BTC, w_ETH; cash = 1 - w_BTC - w_ETH). At the fill each asset's
  change is its own swap against USDC at that asset's open. A leg whose weight change is exactly 0 does not
  trade and pays nothing; a fill bar is a bar where at least one leg trades. Any change > 0 trades, even one of
  round-off size, as in ``reference._simulate``: an order on a book that has not moved since its last fill (flat
  prices, or targets with no room to drift such as 1 - 1e-16 in one coin) can pay gas for ~1e-16 of the book.
- Between fills the book holds coin units and cash, so weights drift with prices; nothing is rebalanced for
  free (TESTING.md bug #4). The portfolio compounds from ``costs.capital_usd``.
- Per bar t >= 1, with per asset a: g_a = open_a[t]/close_a[t-1] - 1, h_a = close_a[t]/open_a[t] - 1,
  r_a = close_a[t]/close_a[t-1] - 1, and w0 = the weights at close t-1:

  - **fill** (target w): drifted_a = w0_a (1+g_a) / (1 + sum_b w0_b g_b), traded_a = |w_a - drifted_a|,
    V_open = V[t-1] (1 + sum w0 g) (USD just before the swaps), leg notional usd_a = traded_a V_open, and
    cost = sum over legs with traded_a > 0 of [traded_a costs.rate(usd_a) + costs.gas_fraction(V_open)]
    (each leg pays the rate of its OWN USD size, and gas per leg). Then

        1 + ret[t] = (1 + sum w0 g)(1 - cost)(1 + sum w h)        w_a[t] = w_a (1+h_a) / (1 + sum w h)

    turnover[t] = sum_a traded_a. The fill re-cuts the book to the target weights of what is left after costs:
    V_after = V_open (1 - cost), coin_a = w_a V_after (in units: w_a V_after / open_a[t]), cash = (1 - sum w)
    V_after. Fees are taken out of what the swaps deliver, so cash and coin units never go negative (spot only);
    the cost of the fill is shared pro rata by the post-trade book, exactly as ``reference._simulate`` does for
    one asset (which the ``constant_mix`` parity needs). A fill whose cost is >= 100% of the portfolio raises.
  - **no fill**: 1 + ret[t] = 1 + sum w0 r and w_a[t] = w0_a (1+r_a) / (1 + sum w0 r); turnover = cost = 0.

  With one coin (w_ETH = 0) these are ``reference._simulate``'s formulas, operation for operation.

Result: a DataFrame on exactly ``bars.index`` with float columns ``ret`` (net return of the whole portfolio,
``ret[0] = 0``), ``position`` (total coin weight w_BTC + w_ETH at the close, after fills and the move through the
bar), ``turnover``, ``cost`` (fraction of the portfolio paid on the bar) and ``w_BTC``, ``w_ETH`` (each coin's
weight at the close). It passes :func:`lab.runner.interface.validate_result`. ``attrs``:

- ``n_trades``: number of fill bars.
- ``trade_returns``: one return per fill bar: the portfolio's return from just before that fill's swaps (V_open,
  before its costs) to just before the next fill's swaps; the last one ends at the last close (marked to
  market, no exit cost). So **prod(1 + trade_returns) = V[n-1] / V_open(first fill)**, and because the book is
  all cash until the first fill, V_open(first fill) = V[0] and prod(1 + trade_returns) = prod(1 + ret). Empty
  when nothing fills. ``len(trade_returns) == n_trades``.
- ``fills``: the per-leg fill log, one row per leg that traded, in time order (BTC before ETH on a bar):
  ``bar`` (row number), ``ts``, ``asset``, ``side`` (``buy``/``sell``), ``units`` (coin units swapped,
  ``usd / price``, before costs), ``price`` (the asset's open), ``usd`` (leg notional ``traded_a * V_open``, the
  size slippage is priced on), ``cost`` (the leg's cost in USD: ``usd * costs.rate(usd) + gas_usd_per_trade``),
  ``weight_before`` (drifted) and ``weight_after`` (target).
- ``orders``: the closes (row numbers) at which an order was sent, all filled at the next open (an order on a
  book already exactly at target trades nothing). The decision at the last close is never sent.
- ``snapshot_id``: the panel's snapshot id (hard rule 7: traceable to the data).

Risk limits: :func:`risk_limits` reads a level's ``min_cash_pct``, ``max_coin_pct`` and drawdown budget from
``config/risk_levels.yaml`` (the only source of those numbers) as fractions, with the file's SHA-256;
:func:`check_targets` says whether :func:`rebalance` accepts given targets under given limits and headroom.

pandas caveat (as in reference.py): ``attrs`` holds arrays and a DataFrame, and pandas copies them onto every
column or slice of the result; drop them (``piece.attrs = {}``) before ``pd.concat`` or ``to_parquet``.
"""

from __future__ import annotations

import copy
import hashlib
import numbers
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from lab.config import CONFIG_DIR
from lab.runner.interface import BAR_COLUMNS, WEIGHT_TOL, validate_bars
from lab.runner.reference import Costs, _check_params, _param_float, _param_int, _real

__all__ = [
    "ASSETS",
    "CASH",
    "FIELDS",
    "LIMIT_TOL",
    "PANEL_ATTRS",
    "WEIGHT_COLUMNS",
    "asset_bars",
    "check_targets",
    "make_panel",
    "random_rebalance",
    "rebalance",
    "risk_limits",
    "validate_panel",
]

ASSETS = ("BTC", "ETH")
CASH = "USDC"  # price 1, no bars
FIELDS = tuple(BAR_COLUMNS)
RISK_LEVELS_FILE = "risk_levels.yaml"
PANEL_COLUMNS = tuple((asset, field) for asset in ASSETS for field in FIELDS)
PANEL_ATTRS = ("snapshot_id", "instruments", "bar_type", "alignment")
WEIGHT_COLUMNS = tuple(f"w_{asset}" for asset in ASSETS)
# A limit counts as breached only beyond float round-off in the weights (they are products of ratios), so a
# target exactly at a limit is allowed and round-off alone never forces a trade.
LIMIT_TOL = WEIGHT_TOL

Targets = tuple[float, ...]
Decide = Callable[[int, Targets], Targets | None]


# ------------------------------------------------------------------------------------------------ the panel


def _named(value) -> bool:
    return isinstance(value, str) and bool(value)


def _per_asset_names(value) -> bool:
    return isinstance(value, Mapping) and set(value) == set(ASSETS) and all(_named(v) for v in value.values())


def validate_panel(bars: pd.DataFrame) -> None:
    """Raise ``ValueError`` unless ``bars`` is a panel in the pinned format (module docstring)."""
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("panel must be a pandas DataFrame")
    cols = bars.columns
    if not isinstance(cols, pd.MultiIndex) or cols.nlevels != 2 or list(cols.names) != ["asset", "field"]:
        raise ValueError("panel columns must be a 2-level MultiIndex named ('asset', 'field')")
    if tuple(cols) != PANEL_COLUMNS:
        raise ValueError(
            f"panel columns must be (asset, field) for assets {ASSETS} and fields {FIELDS}, in that order"
        )
    if not (bars.dtypes == np.float64).all():
        raise ValueError("panel columns must all be float64")
    idx = bars.index
    if (
        not isinstance(idx, pd.DatetimeIndex)
        or idx.tz is None
        or str(idx.tz) != "UTC"
        or idx.unit != "us"
        or idx.name != "ts"
    ):
        raise ValueError(
            "panel index must be a UTC DatetimeIndex named 'ts' in microseconds (bar close times)"
        )
    if not idx.is_monotonic_increasing or idx.has_duplicates:
        raise ValueError("panel index must be strictly increasing (no duplicate closes)")
    attrs = bars.attrs
    if set(attrs) != set(PANEL_ATTRS):
        raise ValueError(f"panel attrs must be exactly {sorted(PANEL_ATTRS)}, got {sorted(attrs, key=str)}")
    if not _named(attrs["snapshot_id"]):
        raise ValueError("panel attrs['snapshot_id'] must be a non-empty string")
    if not _per_asset_names(attrs["instruments"]):
        raise ValueError(f"panel attrs['instruments'] must map each of {ASSETS} to an instrument id")
    if not (_named(attrs["bar_type"]) or _per_asset_names(attrs["bar_type"])):
        raise ValueError(f"panel attrs['bar_type'] must be a bar type string or map each of {ASSETS} to one")
    if not isinstance(attrs["alignment"], Mapping):
        raise ValueError("panel attrs['alignment'] must be a dict")
    for asset in ASSETS:
        try:
            validate_bars(bars[asset])
        except ValueError as exc:
            raise ValueError(f"panel asset {asset}: {exc}") from exc


def make_panel(
    frames: Mapping[str, pd.DataFrame],
    *,
    snapshot_id: str,
    instruments: Mapping[str, str] | None = None,
    bar_type: str | Mapping[str, str] = "synthetic",
    alignment: Mapping | None = None,
) -> pd.DataFrame:
    """A panel from one standard bars frame per asset (e.g. ``lab.data.synthetic.synthetic_market``'s output).

    ``frames`` must hold exactly :data:`ASSETS`, each with the same index (this joins nothing: aligning real data
    is the loader's job). The index becomes UTC microseconds named ``ts``. Defaults, meant for synthetic data:
    ``instruments = {asset: asset}``, ``bar_type = "synthetic"`` and an ``alignment`` that says nothing was
    aligned. The result passes :func:`validate_panel` (else ``ValueError``).
    """
    if not isinstance(frames, Mapping) or set(frames) != set(ASSETS):
        raise ValueError(f"make_panel: frames must map exactly {ASSETS} to bars")
    index = frames[ASSETS[0]].index
    if any(not frames[asset].index.equals(index) for asset in ASSETS):
        raise ValueError("make_panel: every asset needs the same index (align the assets first)")
    for asset in ASSETS:
        try:
            validate_bars(frames[asset])
        except ValueError as exc:
            raise ValueError(f"make_panel: asset {asset}: {exc}") from exc
    values = np.column_stack([frames[a][f].to_numpy(dtype=np.float64) for a, f in PANEL_COLUMNS])
    panel = pd.DataFrame(
        values,
        index=pd.DatetimeIndex(index.tz_convert("UTC").as_unit("us"), name="ts", freq=None),
        columns=pd.MultiIndex.from_tuples(PANEL_COLUMNS, names=["asset", "field"]),
    )
    panel.attrs = {
        "snapshot_id": snapshot_id,
        "instruments": dict(instruments) if instruments is not None else {asset: asset for asset in ASSETS},
        "bar_type": dict(bar_type) if isinstance(bar_type, Mapping) else bar_type,
        "alignment": (
            dict(alignment)
            if alignment is not None
            else {"rule": "make_panel: every asset on the same index (nothing aligned or dropped)"}
        ),
    }
    validate_panel(panel)
    return panel


def asset_bars(bars: pd.DataFrame, asset: str) -> pd.DataFrame:
    """One asset's standard bars frame (``open, high, low, close, volume`` on the panel's index), for the
    single-asset ``reference`` benchmarks (``buy_and_hold``, ``constant_mix``).

    ``attrs`` carries the panel's: ``snapshot_id``, ``alignment`` and ``bar_type`` (this asset's when the panel
    has one per asset), plus ``instrument`` (this asset's id) and ``asset``.
    """
    validate_panel(bars)
    if asset not in ASSETS:
        raise ValueError(f"asset must be one of {ASSETS}, got {asset!r}")
    frame = pd.DataFrame(
        {field: bars[(asset, field)].to_numpy(dtype=np.float64, copy=True) for field in FIELDS},
        index=bars.index.copy(),
    )
    attrs = bars.attrs
    bt = attrs["bar_type"]
    frame.attrs = {
        "snapshot_id": attrs["snapshot_id"],
        "instrument": attrs["instruments"][asset],
        "bar_type": bt[asset] if isinstance(bt, Mapping) else bt,
        "asset": asset,
        "alignment": copy.deepcopy(dict(attrs["alignment"])),
    }
    return frame


# ------------------------------------------------------------------------------------------- risk levels


def _pct_limit(entry: Mapping, key: str) -> float | None:
    if key not in entry:
        return None
    return _real(entry[key], key, 0.0, low_inclusive=True, high=100.0, high_inclusive=True) / 100.0


def _budget(raw) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, numbers.Real):
        return None
    pct = float(raw)
    return pct / 100.0 if 0.0 < pct <= 100.0 else None  # NaN and inf fail the comparison


def risk_limits(level: str = "steady", config_dir: Path | None = None) -> dict:
    """A risk level's limits as ``config/risk_levels.yaml`` sets them, in the units :func:`rebalance` takes.

    The file (owned by the risk-officer) is the only source of these numbers: pass ``min_cash`` and ``max_coin``
    from here to :func:`rebalance`, never typed. The file's bytes are read once; the values come from those bytes
    and ``sha256`` is their hash, so a run can record exactly what it used. Returns:

    - ``level``; ``path`` (the file, as a string); ``sha256``;
    - ``coins``: the level's coin list (a tuple, as written). It must be exactly :data:`ASSETS` plus ``USDC``
      (the cash) in some order, once each: the runner holds nothing else (``ValueError`` otherwise);
    - ``min_cash`` = ``min_cash_pct`` / 100 and ``max_coin`` = ``max_coin_pct`` / 100: ``None`` when the key is
      absent (the level sets no such limit); a present value must be a number in [0, 100] (``ValueError``);
    - ``max_drawdown_budget`` = ``max_drawdown_budget_pct`` / 100 when that is a finite number in (0, 100]; any
      other value (``TBD``, absent, 0, negative, above 100, NaN, a string, a bool) gives ``None``: MISSING, so a
      gate that needs it fails. ``max_drawdown_budget_pct`` is the raw value as read (e.g. ``"TBD"``).

    ``ValueError`` for an unknown level or a level that is not a mapping.
    """
    path = (config_dir or CONFIG_DIR) / RISK_LEVELS_FILE
    data = path.read_bytes()
    levels = yaml.safe_load(data) or {}
    if not isinstance(levels, Mapping) or level not in levels:
        known = sorted(levels, key=str) if isinstance(levels, Mapping) else []
        raise ValueError(f"risk level {level!r} is not in {path} (levels: {known})")
    entry = levels[level]
    if not isinstance(entry, Mapping):
        raise ValueError(f"risk level {level!r} in {path} must be a mapping, got {type(entry).__name__}")
    coins = entry.get("coins")
    expected = sorted((*ASSETS, CASH))
    if not isinstance(coins, list) or not all(isinstance(c, str) for c in coins) or sorted(coins) != expected:
        raise ValueError(
            f"risk level {level!r}: coins must be exactly {expected} in some order (this runner holds BTC and ETH, "
            f"with USDC as cash), got {coins!r}"
        )
    raw_budget = entry.get("max_drawdown_budget_pct")
    return {
        "level": level,
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "coins": tuple(coins),
        "min_cash": _pct_limit(entry, "min_cash_pct"),
        "max_coin": _pct_limit(entry, "max_coin_pct"),
        "max_drawdown_budget": _budget(raw_budget),
        "max_drawdown_budget_pct": raw_budget,
    }


def _prepare(bars: pd.DataFrame, costs: Costs | None) -> Costs:
    validate_panel(bars)
    if costs is None:
        return Costs.from_yaml()
    if not isinstance(costs, Costs):
        raise ValueError(f"costs must be a Costs instance or None, got {type(costs).__name__}")
    return costs


# ------------------------------------------------------------------------------------------------ the engine


def _simulate(bars: pd.DataFrame, costs: Costs, decide: Decide) -> pd.DataFrame:
    """Run ``decide(t, weights at close t)`` at every close (it returns the target vector, or None for no order).

    The order decided at close t fills at the open of t+1, so the decision at the last close is never used.
    """
    m = len(ASSETS)
    o = [bars[(asset, "open")].to_numpy(dtype=float).tolist() for asset in ASSETS]
    c = [bars[(asset, "close")].to_numpy(dtype=float).tolist() for asset in ASSETS]
    n = len(bars)
    ret, pos, turnover, cost = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    weights = [[0.0] * n for _ in range(m)]
    legs: list[tuple[int, int, float, float, float, float]] = []
    orders: list[int] = []
    fill_open: list[float] = []  # V_open just before each fill bar's swaps
    w = [0.0] * m  # weights at the last close
    value = costs.capital_usd  # USD at the last close
    target = decide(0, tuple(w))
    for t in range(1, n):
        if target is not None:
            orders.append(t - 1)
        g = [o[a][t] / c[a][t - 1] - 1.0 for a in range(m)]
        wg = 0.0
        for a in range(m):
            wg += w[a] * g[a]
        drift = 1.0 + wg
        traded = [0.0] * m
        if target is not None:
            drifted = [w[a] * (1.0 + g[a]) / drift for a in range(m)]
            traded = [abs(target[a] - drifted[a]) for a in range(m)]
        total = 0.0
        for a in range(m):
            total += traded[a]
        if total > 0.0:
            h = [c[a][t] / o[a][t] - 1.0 for a in range(m)]
            v_open = value * drift
            gas = costs.gas_fraction(v_open)
            k = 0.0
            for a in range(m):
                if traded[a] > 0.0:
                    usd = traded[a] * v_open
                    rate = costs.rate(usd)
                    k += traded[a] * rate + gas
                    legs.append((t, a, drifted[a], target[a], usd, usd * rate + costs.gas_usd_per_trade))
            if k >= 1.0:
                raise ValueError(
                    f"costs of the fill on {bars.index[t]} are {k:.1%} of a portfolio worth {v_open:.4g} USD: "
                    "it cannot pay them (raise capital_usd or check the cost model)"
                )
            th = 0.0
            for a in range(m):
                th += target[a] * h[a]
            ride = 1.0 + th
            growth = drift * (1.0 - k) * ride
            w = [target[a] * (1.0 + h[a]) / ride for a in range(m)]
            turnover[t], cost[t] = total, k
            fill_open.append(v_open)
        else:
            r = [c[a][t] / c[a][t - 1] - 1.0 for a in range(m)]
            wr = 0.0
            for a in range(m):
                wr += w[a] * r[a]
            growth = 1.0 + wr
            w = [w[a] * (1.0 + r[a]) / growth for a in range(m)]
        ret[t] = growth - 1.0
        value *= growth
        p = 0.0
        for a in range(m):
            p += w[a]
            weights[a][t] = w[a]
        pos[t] = p
        target = decide(t, tuple(w))
    ends = fill_open[1:] + [value] if fill_open else []  # no fill (all-cash targets): no period
    trade_returns = [end / start - 1.0 for start, end in zip(fill_open, ends, strict=True)]
    result = pd.DataFrame(
        {
            "ret": ret,
            "position": pos,
            "turnover": turnover,
            "cost": cost,
            **{col: weights[a] for a, col in enumerate(WEIGHT_COLUMNS)},
        },
        index=bars.index,
        dtype=float,
    )
    result.attrs["trade_returns"] = np.asarray(trade_returns, dtype=float)
    result.attrs["n_trades"] = len(fill_open)
    result.attrs["fills"] = _fills_frame(bars, o, legs)
    result.attrs["orders"] = np.asarray(orders, dtype=np.int64)
    result.attrs["snapshot_id"] = bars.attrs["snapshot_id"]
    return result


def _fills_frame(bars: pd.DataFrame, o: list[list[float]], legs: list[tuple]) -> pd.DataFrame:
    cols = list(zip(*legs, strict=True)) or [()] * 6
    bar = np.asarray(cols[0], dtype=np.int64)
    asset = np.asarray(cols[1], dtype=np.int64)
    before = np.asarray(cols[2], dtype=float)
    after = np.asarray(cols[3], dtype=float)
    usd = np.asarray(cols[4], dtype=float)
    price = np.asarray([o[a][t] for t, a in zip(bar.tolist(), asset.tolist(), strict=True)], dtype=float)
    return pd.DataFrame(
        {
            "bar": bar,
            "ts": bars.index[bar],
            "asset": np.asarray(ASSETS, dtype=object)[asset],
            "side": np.where(after > before, "buy", "sell").astype(object),
            "units": usd / price,
            "price": price,
            "usd": usd,
            "cost": np.asarray(cols[5], dtype=float),
            "weight_before": before,
            "weight_after": after,
        }
    )


# ------------------------------------------------------------------------------------------------ the rules


def _targets(p: Mapping, rule: str) -> Targets:
    w_btc = _param_float(p, "w_btc", low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    w_eth = _param_float(p, "w_eth", low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    if w_btc + w_eth > 1.0:
        raise ValueError(f"{rule}: w_btc + w_eth must be <= 1 (the rest is USDC), got {w_btc!r} + {w_eth!r}")
    return (w_btc, w_eth)


def _limit(p: Mapping, key: str) -> float | None:
    if p.get(key) is None:
        return None
    return _param_float(p, key, low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)


def _breach_test(
    min_cash: float | None, max_coin: float | None, room: float = 0.0
) -> Callable[[Targets], bool]:
    """``breached(w)``: True when the coins together exceed 1 - min_cash - room, or one coin max_coin - room, by
    more than LIMIT_TOL (round-off). ``room = 0`` is the limit itself (the check at every close)."""
    coin_cap = None if min_cash is None else 1.0 - min_cash - room + LIMIT_TOL
    each_cap = None if max_coin is None else max_coin - room + LIMIT_TOL

    def breached(w: Targets) -> bool:
        if coin_cap is not None and w[0] + w[1] > coin_cap:
            return True
        return each_cap is not None and (w[0] > each_cap or w[1] > each_cap)

    return breached


def _checked_targets(p: Mapping) -> tuple[Targets, float | None, float | None]:
    """The targets, min_cash and max_coin of rebalance params, after the target and headroom checks."""
    targets = _targets(p, "rebalance")
    min_cash, max_coin = _limit(p, "min_cash"), _limit(p, "max_coin")
    headroom = _param_float(p, "headroom", 0.0, low=0.0, low_inclusive=True, high=1.0, high_inclusive=True)
    if headroom > 0.0 and min_cash is None and max_coin is None:
        raise ValueError(f"rebalance: headroom = {headroom!r} needs a limit (min_cash or max_coin)")
    if _breach_test(min_cash, max_coin, headroom)(targets):
        raise ValueError(
            f"rebalance: the targets w_btc = {targets[0]!r}, w_eth = {targets[1]!r} break the limits "
            f"min_cash = {min_cash!r}, max_coin = {max_coin!r}, headroom = {headroom!r}"
        )
    return targets, min_cash, max_coin


def check_targets(
    w_btc: float,
    w_eth: float,
    *,
    min_cash: float | None = None,
    max_coin: float | None = None,
    headroom: float = 0.0,
) -> None:
    """Raise ``ValueError`` (the message :func:`rebalance` gives) unless :func:`rebalance` accepts these targets
    under these limits: each target in [0, 1], their sum <= 1, and every set limit at least ``headroom`` away
    (cash target >= min_cash + headroom, each coin target <= max_coin - headroom, up to LIMIT_TOL). For checking
    a search box or a plateau step before any run."""
    _checked_targets(
        {"w_btc": w_btc, "w_eth": w_eth, "min_cash": min_cash, "max_coin": max_coin, "headroom": headroom}
    )


_REBALANCE_PARAMS = frozenset({"w_btc", "w_eth", "band", "every", "min_cash", "max_coin", "headroom"})


def rebalance(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """Hold BTC, ETH and USDC at target weights; rebalance every leg back to target when drift exceeds a band.

    params (unknown keys, missing required keys and bad values raise ``ValueError``):

    - ``w_btc``, ``w_eth`` (required, each in [0, 1], sum <= 1 exactly: no tolerance, so the cash target is never
      negative): target weights; cash (USDC) = 1 - their sum.
    - ``band`` (required, >= 0, absolute): at a check close, order every leg back to target when ANY asset's
      weight at that close differs from its target by more than ``band``. A band >= 1 never rebalances after
      the first buy (a static mix).
    - ``every`` (required, int >= 1): check closes are 0, every, 2*every, ... (rows of the panel), whatever
      orders a breach forced in between.
    - ``min_cash``, ``max_coin`` (optional, in [0, 1]; None = off): the limits, as fractions
      (:func:`risk_limits` reads them from ``config/risk_levels.yaml``; never type them). The targets must
      satisfy them (cash target >= min_cash, each coin target <= max_coin) or ``ValueError``. A breach at ANY
      close, judged on the weights at that close (drifted), forces the full rebalance order at that close,
      whatever ``every`` and ``band`` say. Breach means w_BTC + w_ETH > 1 - min_cash + LIMIT_TOL or a coin >
      max_coin + LIMIT_TOL (LIMIT_TOL = 1e-9, round-off only). With ``headroom`` 0 a target exactly at a limit is
      allowed, but then any move of that coin up breaches it again at the next close.
    - ``headroom`` (optional, in [0, 1], default 0; > 0 needs a limit): the targets must stay at least this far
      inside every set limit (cash target >= min_cash + headroom, each coin target <= max_coin - headroom, up to
      LIMIT_TOL), else ``ValueError``. It constrains the targets only: breaches are still judged at the limits
      themselves, so a run with headroom equals the run without it whenever the targets are accepted. (A live
      account books each leg's fee out of that swap, not pro rata as this engine does, so a target on a limit
      would breach it right after every fill: risk-officer review, rebalance-steady.)

    At close 0 (an empty book) the order buys the targets. Every order fills at the next open (module
    docstring); ``costs=None`` reads ``config/costs.yaml``.
    """
    p = _check_params("rebalance", params, _REBALANCE_PARAMS)
    targets, min_cash, max_coin = _checked_targets(p)
    band = _param_float(p, "band", low=0.0, low_inclusive=True)
    every = _param_int(p, "every")
    breached = _breach_test(min_cash, max_coin)
    costs = _prepare(bars, costs)

    def decide(t: int, w: Targets) -> Targets | None:
        if t == 0 or breached(w):
            return targets
        if t % every:
            return None
        if abs(w[0] - targets[0]) > band or abs(w[1] - targets[1]) > band:
            return targets
        return None

    return _simulate(bars, costs, decide)


def random_rebalance(params: Mapping, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """The luck benchmark for :func:`rebalance`: the same targets, rebalanced at random closes instead of by rule.

    params: ``w_btc``, ``w_eth`` (required, as in :func:`rebalance`); ``n_rebalances`` (required, int >= 0);
    ``seed`` (int >= 0, default 0). Close 0 buys the targets; then ``n_rebalances`` distinct closes drawn
    uniformly from 1..n-2 (seeded; never close 0 and never the last close, whose order could not fill) each order
    every leg back to target, filled at the next open. The draw depends only on ``len(bars)`` and ``seed``, never
    on prices; the drawn closes are in ``attrs["rebalance_closes"]`` (sorted). Raises ``ValueError`` when
    ``n_rebalances > len(bars) - 2``.
    """
    p = _check_params("random_rebalance", params, frozenset({"w_btc", "w_eth", "n_rebalances", "seed"}))
    targets = _targets(p, "random_rebalance")
    n_rebalances = _param_int(p, "n_rebalances", minimum=0)
    seed = _param_int(p, "seed", 0, minimum=0)
    costs = _prepare(bars, costs)
    candidates = len(bars) - 2
    if n_rebalances > candidates:
        raise ValueError(
            f"random_rebalance: {n_rebalances} rebalances don't fit in the {candidates} closes 1..{len(bars) - 2} "
            "(close 0 is the first buy; an order at the last close is never filled)"
        )
    drawn = 1 + np.random.default_rng(seed).choice(candidates, size=n_rebalances, replace=False)
    closes = frozenset(drawn.tolist())
    result = _simulate(bars, costs, lambda t, w: targets if t == 0 or t in closes else None)
    result.attrs["rebalance_closes"] = np.sort(drawn).astype(np.int64)
    return result
