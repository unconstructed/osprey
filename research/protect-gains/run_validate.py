"""protect-gains V1: the single validate look at A10/30d (``research/protect-gains/VALIDATE_PLAN.md``, the
pre-registration committed at ``55e0dd4``; section numbers below are that file's).

SCOUTING ONLY, like run 0: the reference engine (``lab.runner.portfolio`` driven by ``lab.runner.protect``, unchanged),
the PLACEHOLDER costs of ``config/costs.yaml`` and exchange candles in place of Base prices. A pass makes nothing ready
for paper and is not a lab default. It reads the train and validate windows only: every panel comes from
``lab.data.panel.load_panel`` with ``last_close`` = 2024-07-01 00:00 UTC (the last validate close), through a loader
that refuses a request or a returned close after it. The test window is never read.

    uv run python research/protect-gains/run_validate.py                                   # THE look (real data, once)
    uv run python research/protect-gains/run_validate.py --synthetic 7 --out-dir <scratch>  # dry run

Start refusals, before anything is written (exit 2): a real look uses the pinned folders only (results/protect-gains,
config/, data/catalog/) and a dry run never writes into results/protect-gains or anywhere in the repo; the RUNLOG holds
a validate look, ``<out>/validate/`` exists or the tracked ``validate_look.json`` exists (one look, section 7); a real
look on a dirty git tree; VALIDATE_PLAN.md not the committed pre-registration (its SHA-256); the Steady limits as read
refusing a mix, or the tool's limit as read not 2 (run.py's guards).

Then, before any bar is read (section 7): ``<out>/validate/STARTED``, the start record ``start.json`` (commit, config
hash, snapshot, VALIDATE_PLAN.md's SHA-256) and one RUNLOG line (``"event": "validate look V1"``). From here on the look
is spent: a stop (exit 3) or a crash (re-raised) writes ``look.json`` and the tracked ``validate_look.json`` with the
outcome INCONCLUSIVE and the error, and a RUNLOG event line. The steps: the snapshot pins (section 3), the panels (the
test-window guard; the train part's rows and, on real data, its panel hash; the 547 validate rows), the index of each
source and f over the whole panel, the 768 runs of section 5 with run 0's consistency checks on every run, the count,
``runs.parquet`` and ``stops.parquet`` (before any check), the checks V-a, V-b, V-c and the verdict (section 6, pure
functions over the runs table below), and the outputs: ``look.json`` in ``<out>/validate/``; the tracked
``validate_runs.csv``, ``validate_look.json`` and the RUNLOG event line in this folder (dry runs: ``<out>/tracked/``).
Exit codes: 0 done (any verdict), 2 refused at start, 3 stopped (INCONCLUSIVE).

``research/`` is never imported by ``lab/``. This file reuses ``run.py``'s helpers (loaded as ``protect_gains_run``).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data import catalog
from lab.data.external import HoldoutWindowError
from lab.data.panel import instruments, load_panel
from lab.data.synthetic import synthetic_market
from lab.runner import holdmix as H
from lab.runner import protect as P
from lab.runner.steady import panel_hash

HERE = Path(__file__).resolve().parent
RUN_MODULE = "protect_gains_run"  # the name the tests load run.py under, so both share one module object


def _load_run():
    if RUN_MODULE not in sys.modules:
        spec = importlib.util.spec_from_file_location(RUN_MODULE, HERE / "run.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[RUN_MODULE] = module
        spec.loader.exec_module(module)
    return sys.modules[RUN_MODULE]


R = _load_run()

SCRIPT = "run_validate.py"
LOOK = "V1"
EVENT = "validate look V1"  # section 7
VALIDATE_PLAN = HERE / "VALIDATE_PLAN.md"
VALIDATE_PLAN_SHA256 = (
    "dc9041f06ec2985d2d016ca7d9ef7e92e7ea1fe926dc0b8e8fd811c1bfdca80f"  # as committed at 55e0dd4
)
LOOK_FOLDER = "validate"
INTERVAL = R.INTERVAL
LAST_TRAIN = R.LAST_CLOSE  # 2023-01-01 00:00 UTC: the train part ends here (PLAN.md section 3's panel hashes)
CUT = pd.Timestamp(
    "2024-07-01", tz="UTC"
)  # the last validate close (section 3); the test window is never read
VALIDATE_FIRST = pd.Timestamp("2023-01-02", tz="UTC")
VALIDATE_ROWS = 547  # section 3 (V0b): 2023-01-02 .. 2024-07-01, none missing
N_WINDOWS = 7  # section 4: j = 0..6
WINDOW_MONTHS = 12
FULL = "full"
SOURCES = H.SOURCES
COST_LEVELS = R.COST_LEVELS
REF = P.REF_LINE  # "R"
CANDIDATE = "A10/30d counts"
SETTINGS: dict[str, tuple | None] = {  # section 5: per (source, cost, window, mix), four runs
    REF: None,
    CANDIDATE: ("A", 0.10, "wait30", "counts"),
    "A10/30d separate": ("A", 0.10, "wait30", "separate"),
    "A10/trend counts": ("A", 0.10, "trend", "counts"),
}
HEADLINE_POOL = ("KRAKEN", "1x")  # section 6
ROBUSTNESS_POOLS = (("BINANCE", "1x"), ("KRAKEN", "2x"))
C_MAX = 0.10  # V-a: the median of C at most 0.10
PERCENTILE = P.PERCENTILE  # 90, numpy.percentile (linear)
RESTOP_MAX = P.RESTOP_MAX  # V-c: run 0's D2 rule, 25%
PASS, FAIL, MISSING = "PASS", "FAIL", P.MISSING
HOLDS, NOT_HOLDS, INCONCLUSIVE = "HOLDS UP", "DOES NOT HOLD UP", "INCONCLUSIVE"
SAME, DIFFERS = "same", "differs"
LABEL = (
    "SCOUTING, placeholder costs, reference engine; the single validate look V1 (2023-01-02 .. 2024-07-01) at a "
    "post-hoc pick (A10/30d): not a lab default"
)

INTERPRETATIONS = {
    "windows": "Window j (j = 0..6, labelled 'j0'..'j6') holds the closes from the 2nd of M_j = January 2023 + j "
    "months to the 1st of M_(j+12), both included, at 00:00 UTC; the full span ('full') 2023-01-02 .. 2024-07-01. "
    "Each slice must hold exactly its daily closes (holdmix.window_slice with no missing close: none is missing in "
    "the validate window, section 3)",
    "pool": "The pool of a (source, cost) is its 12-month windows (j0..j6, never the full span): for a setting, its 42 "
    "runs and R's 42 runs on the same (mix, window) pairs",
    "V-a": "PASS when numpy.median of C over the setting's pool runs is <= 0.10 (exactly 0.10 passes)",
    "V-b": "PASS when numpy.percentile(F, 90) (linear) over the setting's pool runs is <= R's over its pool runs, and "
    "the setting's worst F (the largest) is <= R's worst F (equal passes)",
    "V-c": "The share is the pool's re-stops summed over its buy-backs summed (run 0's D2 share, pooled). PASS when "
    "it is <= 0.25 (exactly 0.25 passes); with no buy-back in the pool the share is MISSING and V-c is FAIL",
    "missing": "A failed run (the setting's or R's) in a pool makes V-a, V-b, V-c and the verdict on that pool "
    "MISSING; a pool with no runs is MISSING too",
    "verdict": "HOLDS UP when V-a and V-b pass, DOES NOT HOLD UP when either fails, MISSING when a run in the pool "
    "failed; on a stop or crash after STARTED the outcome is INCONCLUSIVE",
    "headline": "'<verdict>; whipsaw <V-c>' on the Kraken 1x pool for A10/30d 'counts' (e.g. 'HOLDS UP; whipsaw "
    "FAIL'); 'INCONCLUSIVE' after a stop or crash",
    "robustness": "The same checks on the Binance 1x and Kraken 2x pools; the label is 'same' when that pool's "
    "'<verdict>; whipsaw <V-c>' equals the headline, else 'differs' (decides nothing)",
    "ahead": "A run ended ahead of the tool alone when C < 0 (V_end above R's); ahead_share is the share of the "
    "setting's pool runs that did. fire_rate is the share with at least one filled stop",
    "descriptions": "look.json also holds: the checks per mix (each mix's 7 runs, same rules) on every pool; the "
    "same checks for every setting ('separate' and A10/trend against R) on every pool, with C's mean; the full-span "
    "runs (one row per run); every stop of A10/30d 'counts' on every pool (12-month and full span) with its date and "
    "overshoot. stops.parquet holds every stop of every brake run",
    "snapshot": "Section 3's pins (snapshot id 1746a21b75683e76 and the bars hash) are checked after STARTED, as "
    "section 3 says ('any difference stops the look (INCONCLUSIVE, and the look is spent)'); SNAPSHOT.json is read "
    "(metadata only, no bar) for the start record before STARTED is written. Dry runs record 'synthetic'",
    "data": "The train part is the rows with close <= 2023-01-01: its rows must be 2190 / 1963 and, on real data, its "
    "steady.panel_hash PLAN.md section 3's. The validate part must be exactly the 547 daily closes 2023-01-02 .. "
    "2024-07-01 and the panel nothing else. The panels are recorded in start.json before the checks",
    "test_window": "The loader is wrapped: a request with no end or an end after 2024-07-01 00:00 UTC, or a returned "
    "close after it (a tz-naive index is read as UTC), stops the look before load_panel sees the bars (load_panel "
    "refuses them too); the panel's last close is checked again. INCONCLUSIVE, reported to the owner",
    "index": "I and its SMA200 (protect.index_signal) over each source's whole loaded panel (2017 .. 2024-07-01), "
    "cut to each window with protect.signal_rows: rows before a window are history",
    "one_look": "Refused when the RUNLOG holds any line whose event starts with 'validate look' (whatever its data), "
    "when <out>/validate/ exists, or when the tracked validate_look.json exists. A dry run's RUNLOG and tracked "
    "copies are in <out>/tracked/",
    "inconclusive": "After STARTED, a stop (the snapshot, data and test-window checks, a consistency check, the "
    "count, a hashed file changing) or a crash writes look.json and the tracked validate_look.json (INCONCLUSIVE, "
    "with the error) and a RUNLOG event line, and keeps the runs computed so far in runs.parquet / stops.parquet "
    "(a block that stops is not written, as in run 0); exit 3 for a stop, the crash is re-raised",
    "failures": "A run that raises (other than a consistency error) is logged as failed with its error (look.json's "
    "failed_runs holds the traceback) and the look goes on; C of a brake run whose R failed is NaN",
    "consistency": "As run 0 (PLAN.md section 9): R against holdmix.hold_mix bit for bit, its orders and book; each "
    "brake run's events, orders and book; every run's fee check and fee split; then the count (768, no run id "
    "twice, 672 twelve-month and 96 full-span runs); at the end every hashed file hashed again",
    "config_hash": "run.py's hashed files plus VALIDATE_PLAN.md and this script, and the pinned values below",
    "plan_sha": "VALIDATE_PLAN.md must hash to the committed pre-registration (55e0dd4), else the look is refused at "
    "start",
    "limits": "run.py's guards at start: risk_limits('steady') with both limits, the six mixes passing check_targets "
    "with h = 0.02, and the tool's limit as read equal to 2; the tool at band 0.30 and a 15-day wait",
    "csv": "validate_runs.csv is one row per run: its keys, status, F, C and the brake measures; no Sharpe, total "
    "return, end value or profit-share column",
    "order": "Runs are made and listed in the order sources (Kraken, Binance) x costs (1x, 2x) x windows (j0..j6, "
    "full) x mixes x settings (R first), in one process",
}


class Stop(Exception):
    """The look stopped after STARTED (exit 3, INCONCLUSIVE): ``kind`` is 'test window', 'data' or 'consistency'."""

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind


Refusal = R.Refusal


# ------------------------------------------------------------------------------------------------ the grid


@dataclass(frozen=True)
class Grid:
    """What the look runs: sources x costs x windows x mixes x settings (R first)."""

    sources: tuple[str, ...]
    costs: tuple[str, ...]
    windows: tuple[str, ...]
    mixes: tuple[tuple[float, float], ...]
    settings: tuple[str, ...]
    name: str = "plan"


def windows() -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """Section 4's windows from the calendar: ``(label, first close, last close)`` for j0..j6, then the full span."""
    month0 = pd.Timestamp("2023-01-01", tz="UTC")
    out = [
        (
            f"j{j}",
            month0 + pd.DateOffset(months=j) + pd.Timedelta(days=1),
            month0 + pd.DateOffset(months=j + WINDOW_MONTHS),
        )
        for j in range(N_WINDOWS)
    ]
    out.append((FULL, VALIDATE_FIRST, CUT))
    return out


PLAN_GRID = Grid(
    sources=SOURCES,
    costs=COST_LEVELS,
    windows=tuple(label for label, _, _ in windows()),
    mixes=P.MIXES,
    settings=tuple(SETTINGS),
)


def expected_count(grid: Grid) -> dict:
    """Section 5's count for ``grid``: sources x costs x windows x mixes x settings (768 for the plan's grid: 672 on
    the 12-month windows and 96 on the full span)."""
    per_window = len(grid.sources) * len(grid.costs) * len(grid.mixes) * len(grid.settings)
    twelve = sum(1 for w in grid.windows if w != FULL)
    full = len(grid.windows) - twelve
    return {
        "total": per_window * len(grid.windows),
        "twelve_month": per_window * twelve,
        "full_span": per_window * full,
    }


def thresholds() -> dict:
    return {"C_MAX": C_MAX, "PERCENTILE": PERCENTILE, "RESTOP_MAX": RESTOP_MAX, "RESTOP_DAYS": P.RESTOP_DAYS}


def pinned_values() -> dict:
    return R.jsonable(
        {
            "grid": asdict(PLAN_GRID),
            "windows": windows(),
            "settings": SETTINGS,
            "candidate": CANDIDATE,
            "headline_pool": HEADLINE_POOL,
            "robustness_pools": ROBUSTNESS_POOLS,
            "thresholds": thresholds(),
            "tool": {"band": P.TOOL_BAND, "cap": P.TOOL_CAP, "wait": P.TOOL_WAIT, "headroom": P.HEADROOM},
            "deposit": P.DEPOSIT,
            "stress": R.STRESS,
            "snapshot_id": R.SNAPSHOT_ID,
            "bars_sha256": R.BARS_SHA256,
            "panel_hashes": R.PANEL_HASHES,
            "train_rows": R.ROWS,
            "validate_rows": VALIDATE_ROWS,
            "last_train": LAST_TRAIN,
            "cut": CUT,
            "plan_sha256": VALIDATE_PLAN_SHA256,
        }
    )


# ------------------------------------------------------------------------------------- hashing, guards


def frozen_paths() -> list[str]:
    """run.py's hashed files plus VALIDATE_PLAN.md and this script (INTERPRETATIONS["config_hash"]), sorted."""
    return sorted(
        {
            *R.frozen_paths(),
            "research/protect-gains/VALIDATE_PLAN.md",
            "research/protect-gains/run_validate.py",
        }
    )


def file_hashes(config_dir: Path | None = None) -> dict[str, str]:
    cfg = Path(config_dir) if config_dir is not None else R.CONFIG_DIR
    return {
        rel: R.sha256_file(cfg / Path(rel).name if rel in R.CONFIG_FILES else R.REPO / rel)
        for rel in frozen_paths()
    }


def config_hash(hashes: Mapping[str, str]) -> str:
    blob = json.dumps({"files": dict(sorted(hashes.items())), "pinned": pinned_values()}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def holds_a_look(entries: Sequence[Mapping]) -> bool:
    """Whether a RUNLOG holds a validate look (INTERPRETATIONS["one_look"])."""
    return any(str(e.get("event", "")).startswith("validate look") for e in entries)


def read_snapshot(catalog_dir: Path, synthetic: bool) -> dict:
    """``snapshot_id`` and ``bars_content_sha256`` from ``SNAPSHOT.json`` (metadata only, no bar), never refused here:
    section 3's pins are checked after STARTED (:func:`check_snapshot`)."""
    if synthetic:
        return {"snapshot_id": "synthetic", "bars_content_sha256": "synthetic"}
    path = Path(catalog_dir) / catalog.SNAPSHOT_FILE
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return {"snapshot_id": None, "bars_content_sha256": None, "error": f"cannot read {path}: {exc}"}
    return {"snapshot_id": data.get("snapshot_id"), "bars_content_sha256": data.get("bars_content_sha256")}


def check_snapshot(snapshot: Mapping, synthetic: bool) -> None:
    """Section 3's pins (real data): the snapshot id and the bars hash, else stop."""
    if synthetic:
        return
    got = (snapshot.get("snapshot_id"), snapshot.get("bars_content_sha256"))
    if got != (R.SNAPSHOT_ID, R.BARS_SHA256):
        raise Stop(
            "data",
            f"the catalog's snapshot {got} is not ({R.SNAPSHOT_ID!r}, {R.BARS_SHA256!r}) (VALIDATE_PLAN.md section 3)"
            + (f"; {snapshot['error']}" if snapshot.get("error") else ""),
        )


def start_guards(args) -> dict:
    """Every start refusal (module docstring), before anything is written."""
    synthetic = args.synthetic is not None
    out = Path(args.out_dir) if args.out_dir else R.DEFAULT_OUT
    catalog_dir = Path(args.catalog_dir) if args.catalog_dir else R.DEFAULT_CATALOG
    config_dir = Path(args.config_dir) if args.config_dir else None
    if synthetic:
        R.check_out_dir(out)
    else:
        R.check_real_paths(out, config_dir, catalog_dir)
    tracked = R.tracked_dir(out, synthetic)
    log = tracked / "RUNLOG.jsonl"
    if holds_a_look(R.runlog_entries(log)):
        raise Refusal(
            f"{log} already holds a validate look: the validate window is spent for this study (section 7)"
        )
    if (out / LOOK_FOLDER).exists():
        raise Refusal(f"{out / LOOK_FOLDER} exists: the validate look runs once (section 7)")
    if (tracked / "validate_look.json").exists():
        raise Refusal(f"{tracked / 'validate_look.json'} exists: the validate look runs once (section 7)")
    plan_sha = R.sha256_file(VALIDATE_PLAN)
    if plan_sha != VALIDATE_PLAN_SHA256:
        raise Refusal(
            f"VALIDATE_PLAN.md hashes to {plan_sha}, not the committed pre-registration's {VALIDATE_PLAN_SHA256}"
        )
    git = R.git_state()
    if git["dirty"] and not synthetic:
        raise Refusal(
            "the git tree is dirty (git status --porcelain --untracked-files=all): commit first (section 7). "
            f"Changes: {git['changes'][:10]}"
        )
    limits = R.steady_limits(config_dir)
    R.check_mixes(PLAN_GRID.mixes, limits)
    return {
        "out": out,
        "look_dir": out / LOOK_FOLDER,
        "tracked": tracked,
        "log": log,
        "config_dir": config_dir,
        "catalog_dir": catalog_dir,
        "synthetic": synthetic,
        "data": "synthetic" if synthetic else "real",
        "git": git,
        "plan_sha256": plan_sha,
        "hashes": file_hashes(config_dir),
        "snapshot": read_snapshot(catalog_dir, synthetic),
        "limits": limits,
        "costs": R.cost_models(config_dir),
    }


# ------------------------------------------------------------------------------------------------ the data

SYNTHETIC_DAYS = 2738  # closes 2017-01-02 .. 2024-07-01


def synthetic_bar_loader(seed: int, days: int = SYNTHETIC_DAYS) -> Callable:
    """run.py's synthetic stand-in for ``lab.data.catalog.load_bars``, extended to the last validate close: SYNTHETIC
    daily bars from close 2017-01-02 (Kraken, ETH's 2018-01-13 bar missing) or 2017-08-18 (Binance, the same bars
    times a small per-bar factor), for dry runs and tests only. Snapshot id ``"synthetic"``."""
    ids = {inst: (src, asset) for src in SOURCES for asset, inst in instruments(src).items()}
    market: dict[str, pd.DataFrame] = {}

    def loader(instrument, interval, start=None, end=None, catalog_dir=None) -> pd.DataFrame:
        if interval != INTERVAL or instrument not in ids:
            raise ValueError(f"synthetic loader: no {instrument!r} {interval!r} bars")
        if not market:
            market.update(synthetic_market(days, seed=seed, start=R.SYNTHETIC_FIRST))
        source, asset = ids[instrument]
        bars = market[asset].copy()
        bars.index = pd.DatetimeIndex(bars.index, name="ts").as_unit("us")
        if asset == "ETH":
            for missing in H.MISSING_CLOSES[source]:
                bars = bars.drop(missing)
        if source == "BINANCE":
            rng = np.random.default_rng([seed, 7, ("BTC", "ETH").index(asset)])
            factor = np.exp(rng.normal(0.0, 0.001, len(bars)))
            for col in ("open", "high", "low", "close"):
                bars[col] = bars[col].to_numpy() * factor
            bars = bars.loc[H.FIRST_CLOSE[source] :]
        if start is not None:
            bars = bars.loc[pd.Timestamp(start) :]
        if end is not None:
            bars = bars.loc[: pd.Timestamp(end)]
        bars.attrs = {
            "snapshot_id": "synthetic",
            "bar_type": catalog.bar_type(instrument, interval),
            "instrument": instrument,
        }
        return bars

    return loader


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def guarded(loader: Callable | None) -> Callable:
    """The loader ``load_panel`` calls, wrapped (INTERPRETATIONS["test_window"]): a request ending after
    2024-07-01 00:00 UTC (or with no end) is refused before the inner loader is called, and a returned close after it
    raises ``HoldoutWindowError`` before ``load_panel`` sees the bars. ``None`` means ``lab.data.catalog.load_bars``,
    looked up at call time."""

    def call(instrument, interval, start=None, end=None, catalog_dir=None):
        if end is None or _utc(end) > CUT:
            raise HoldoutWindowError(
                f"{instrument}: a request ending at {end} reaches past the last validate close {CUT.isoformat()}"
            )
        inner = catalog.load_bars if loader is None else loader
        frame = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
        index = getattr(frame, "index", None)
        if isinstance(index, pd.DatetimeIndex) and len(index):
            latest = _utc(index.max())
            if latest > CUT:
                raise HoldoutWindowError(
                    f"{instrument}: the loader returned a close {latest.isoformat()} after the last validate close "
                    f"{CUT.isoformat()}"
                )
        return frame

    return call


def load_look_panel(source: str, *, catalog_dir: Path, config_dir: Path | None, loader: Callable | None):
    """``load_panel(source, "1d", last_close=2024-07-01 00:00 UTC)`` through :func:`guarded`."""
    try:
        return load_panel(
            source,
            INTERVAL,
            last_close=CUT,
            catalog_dir=catalog_dir,
            config_dir=config_dir,
            loader=guarded(loader),
        )
    except HoldoutWindowError as exc:
        raise Stop(
            "test window", f"{source}: {exc}. Nothing from it is used; report the incident to the owner"
        ) from exc
    except ValueError as exc:
        raise Stop("data", f"load_panel refused the {source} bars: {exc}") from exc


def data_record(panel: pd.DataFrame) -> dict:
    """The train and validate parts of a loaded panel, as checked by :func:`check_panel`."""
    train = panel.loc[:LAST_TRAIN]
    return {
        "train_rows": len(train),
        "train_hash": panel_hash(train) if len(train) else None,
        "validate_rows": len(panel) - len(train),
        "last_close": panel.index[-1],
    }


def check_panel(source: str, panel: pd.DataFrame, synthetic: bool) -> None:
    """Section 3's data checks (INTERPRETATIONS["data"]); any difference stops the look."""
    latest = _utc(panel.index.max())
    if latest > CUT:
        raise Stop(
            "test window", f"{source}: the panel holds a close {latest.isoformat()} after {CUT.isoformat()}"
        )
    train = panel.loc[:LAST_TRAIN]
    if len(train) != R.ROWS[source]:
        raise Stop(
            "data",
            f"{source}: the train part has {len(train)} rows, expected {R.ROWS[source]} (PLAN.md section 3)",
        )
    if not synthetic:
        got = panel_hash(train)
        if got != R.PANEL_HASHES[source]:
            raise Stop("data", f"{source}: the train part's panel hash {got} is not {R.PANEL_HASHES[source]}")
    try:
        part = H.window_slice(panel, VALIDATE_FIRST, CUT)
    except H.WindowSliceError as exc:
        raise Stop("data", f"{source}: the validate part: {exc} (section 3: 547 rows, none missing)") from exc
    if len(part) != VALIDATE_ROWS or len(panel) != len(train) + len(part):
        raise Stop(
            "data",
            f"{source}: {len(panel)} rows = {len(train)} train + {len(part)} validate + "
            f"{len(panel) - len(train) - len(part)} others; expected {VALIDATE_ROWS} validate rows and no others",
        )


# ------------------------------------------------------------------------------------- the runs of a block

KEY_COLUMNS = (
    "run_id",
    "source",
    "cost",
    "window",
    "setting",
    "line",
    "level",
    "mode",
    "reading",
    "s",
    "f",
    "w_btc",
    "w_eth",
    "first_close",
    "last_close",
    "rows",
)
RUN_COLUMNS = (*KEY_COLUMNS, "status", "error", *P.RUN_MEASURES, "C", "snapshot_id", "commit")
STOP_TABLE_COLUMNS = ("run_id", "source", "cost", "window", "setting", "s", "f", *P.STOP_COLUMNS)
TEXT_COLUMNS = (
    "run_id",
    "source",
    "cost",
    "window",
    "setting",
    "line",
    "mode",
    "reading",
    "status",
    "error",
    "snapshot_id",
    "commit",
)
INT_COLUMNS = tuple(c for c in R.INT_COLUMNS if c != "window")
CSV_COLUMNS = (
    "run_id",
    "source",
    "cost",
    "window",
    "setting",
    "line",
    "level",
    "mode",
    "reading",
    "s",
    "f",
    "first_close",
    "last_close",
    "rows",
    "status",
    "F",
    "C",
    "stops",
    "fired",
    "first_stop_days",
    "unfilled",
    "not_bought_back",
    "buybacks",
    "restops",
    "buyback_held",
    "usdc_days",
    "usdc_share",
    "overshoot_max",
    "tool_orders",
    "fees_pct_per_year_tool",
    "fees_pct_per_year_brake",
    "gas_pct_per_year_tool",
    "gas_pct_per_year_brake",
    "passes",
)
FORBIDDEN_CSV = R.FORBIDDEN_CSV


def run_id(source: str, cost: str, window: str, s: float, f: float, setting: str) -> str:
    spec = SETTINGS[setting]
    if spec is None:
        tail = f"{REF}:-:none:none"
    else:
        line, level, mode, reading = spec
        tail = f"{line}:{level:g}:{mode}:{reading}"
    return f"{LOOK}:{source}:{cost}:{window}:{s:g}:{f:g}:{tail}"


def frame(rows: list[dict], columns: Sequence[str]) -> pd.DataFrame:
    """Rows to a frame with stable dtypes (run.py's ``_frame`` with ``window`` as text)."""
    out = pd.DataFrame(rows, columns=list(columns))
    for col in out.columns:
        if col in R.TIME_COLUMNS:
            out[col] = pd.to_datetime(out[col], utc=True).astype("datetime64[us, UTC]")
        elif col in INT_COLUMNS:
            out[col] = out[col].fillna(-1).astype("int64")
        elif col in R.BOOL_COLUMNS:
            out[col] = out[col].fillna(False).astype(bool)
        elif col in TEXT_COLUMNS:
            out[col] = out[col].astype(object)
        else:
            out[col] = out[col].astype("float64")
    return out


def block(ctx: Mapping, source: str, cost: str, window: str) -> dict:
    """The runs of one (source, cost, window): for each mix, R and the brake settings (section 5), each with run 0's
    consistency checks. A consistency error stops the look; any other error is a failed run, logged."""
    grid: Grid = ctx["grid"]
    first, last = ctx["windows"][window]
    try:
        piece = H.window_slice(ctx["panels"][source], first, last)
    except H.WindowSliceError as exc:
        raise Stop("data", f"{source} window {window}: {exc}") from exc
    costs = ctx["costs"][cost]
    common = {
        "source": source,
        "cost": cost,
        "window": window,
        "first_close": first,
        "last_close": last,
        "rows": len(piece),
        "snapshot_id": ctx["snapshot_id"],
        "commit": ctx["commit"],
    }
    runs, stops, failures = [], [], []
    for s, f in grid.mixes:
        targets = H.mix_targets(s, f)
        tp = P.tool_params(targets, ctx["limits"])
        sig = P.signal_rows(ctx["signals"][(source, f)], piece.index)
        v_ref = math.nan
        for setting in grid.settings:
            spec = SETTINGS[setting]
            line, level, mode, reading = spec if spec is not None else (REF, math.nan, "none", "none")
            base = {
                **common,
                "run_id": run_id(source, cost, window, s, f, setting),
                "setting": setting,
                "line": line,
                "level": float(level),
                "mode": mode,
                "reading": reading,
                "s": float(s),
                "f": float(f),
                "w_btc": targets[0],
                "w_eth": targets[1],
            }
            try:
                if spec is None:
                    res = R._reference(tp, piece, costs)
                    measures, rows = P.run_measures(res, piece, costs, None)
                else:
                    params = {**tp, "line": line, "level": level, "mode": mode, "reading": reading}
                    res = P.protect(params, piece, costs, sig)
                    R._brake_checks(res, piece, costs, sig, reading)
                    measures, rows = P.run_measures(res, piece, costs, sig)
            except P.ConsistencyError as exc:
                raise Stop("consistency", f"{base['run_id']}: {exc}") from exc
            except Exception as exc:  # a failed run is logged and the look goes on
                error = f"{type(exc).__name__}: {exc}"
                runs.append(R._row(base, "failed", error))
                failures.append(
                    {"run_id": base["run_id"], "error": error, "traceback": traceback.format_exc()}
                )
                continue
            if spec is None:
                v_ref = measures["v_end"]
                c = 0.0
            else:
                c = P.cost_vs_reference(measures["v_end"], v_ref) if math.isfinite(v_ref) else math.nan
            runs.append(R._row(base, P.OK, measures={**measures, "C": c}))
            keys = {k: base[k] for k in ("run_id", "source", "cost", "window", "setting", "s", "f")}
            stops += [{**keys, **row} for row in rows]
    return {"runs": runs, "stops": stops, "failures": failures}


def check_count(runs: pd.DataFrame, grid: Grid) -> dict:
    """Every run logged: section 5's count for ``grid`` (768), failures included, no run id twice; else stop."""
    want = expected_count(grid)
    full = runs["window"].to_numpy() == FULL
    got = {"total": len(runs), "twelve_month": int((~full).sum()), "full_span": int(full.sum())}
    if got != want:
        raise Stop("consistency", f"the look logged {got} runs, expected {want} (VALIDATE_PLAN.md section 5)")
    if runs["run_id"].duplicated().any():
        raise Stop("consistency", "two runs share a run id")
    return {"got": got, "expected": want}


# ------------------------------------------------------------------------------------------------ the checks


def select(
    runs: pd.DataFrame, source: str, cost: str, setting: str, *, full: bool = False, mix=None
) -> pd.DataFrame:
    """A setting's runs on one (source, cost): its 12-month windows (the pool), or the full span; one mix or all."""
    mask = (
        (runs["source"].to_numpy() == source)
        & (runs["cost"].to_numpy() == cost)
        & (runs["setting"].to_numpy() == setting)
        & ((runs["window"].to_numpy() == FULL) == full)
    )
    if mix is not None:
        mask &= (runs["s"].to_numpy() == mix[0]) & (runs["f"].to_numpy() == mix[1])
    return runs[mask]


def _pairs(frame: pd.DataFrame) -> list[tuple]:
    return sorted(zip(frame["s"].tolist(), frame["f"].tolist(), frame["window"].tolist(), strict=True))


def checks(cand: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """V-a, V-b, V-c and the verdict (section 6) for a setting's runs ``cand`` against R's runs ``ref`` on the same
    (mix, window) pairs (INTERPRETATIONS["V-a"] .. ["verdict"]), with the descriptive numbers."""
    out = {
        "runs": len(cand),
        "ref_runs": len(ref),
        "V-a": MISSING,
        "V-b": MISSING,
        "V-c": MISSING,
        "verdict": MISSING,
        "reason": None,
    }
    if cand.empty or ref.empty:
        out["reason"] = "no runs in the pool"
        return out
    if _pairs(cand) != _pairs(ref):
        raise ValueError("checks: the setting's runs and R's do not hold the same (mix, window) pairs")
    if (cand["status"].to_numpy() != P.OK).any() or (ref["status"].to_numpy() != P.OK).any():
        out["reason"] = "a run in the pool failed"
        return out
    c = cand["C"].to_numpy(dtype=float)
    f, f0 = cand["F"].to_numpy(dtype=float), ref["F"].to_numpy(dtype=float)
    c_med = float(np.median(c))
    q, q0 = float(np.percentile(f, PERCENTILE)), float(np.percentile(f0, PERCENTILE))
    worst, worst0 = float(f.max()), float(f0.max())
    buybacks, restops = int(cand["buybacks"].sum()), int(cand["restops"].sum())
    share = restops / buybacks if buybacks else MISSING
    va = PASS if c_med <= C_MAX else FAIL
    vb = PASS if q <= q0 and worst <= worst0 else FAIL
    vc = PASS if not isinstance(share, str) and share <= RESTOP_MAX else FAIL
    out.update(
        {
            "V-a": va,
            "V-b": vb,
            "V-c": vc,
            "verdict": HOLDS if va == PASS and vb == PASS else NOT_HOLDS,
            "C_med": c_med,
            "C_mean": float(np.mean(c)),
            "Q": q,
            "Q0": q0,
            "worst_F": worst,
            "worst_F0": worst0,
            "buybacks": buybacks,
            "restops": restops,
            "restop_share": share,
            "ahead_share": float(np.mean(c < 0.0)),
            "fire_rate": float(np.mean(cand["fired"].to_numpy(dtype=bool))),
            "stops": int(cand["stops"].sum()),
            "usdc_share_median": float(np.median(cand["usdc_share"].to_numpy(dtype=float))),
        }
    )
    return out


def headline(result: Mapping) -> str:
    """'<verdict>; whipsaw <V-c>' (section 6)."""
    return f"{result['verdict']}; whipsaw {result['V-c']}"


def pool_checks(runs: pd.DataFrame, source: str, cost: str, setting: str = CANDIDATE, mix=None) -> dict:
    """:func:`checks` on one pool (the 12-month windows of ``source`` and ``cost``), optionally one mix, with its
    headline text."""
    ch = checks(select(runs, source, cost, setting, mix=mix), select(runs, source, cost, REF, mix=mix))
    return {**ch, "headline": headline(ch)}


def _name(source: str, cost: str) -> str:
    return f"{source} {cost}"


def _mix_name(mix) -> str:
    return f"{mix[0]:g}/{mix[1]:g}"


FULL_SPAN_COLUMNS = (
    "source",
    "cost",
    "s",
    "f",
    "setting",
    "status",
    "F",
    "C",
    "stops",
    "buybacks",
    "restops",
    "usdc_share",
    "overshoot_max",
    "fees_pct_per_year_brake",
)
STOP_SUMMARY = (
    "window",
    "s",
    "f",
    "stop_ts",
    "high",
    "line_value",
    "v_sale",
    "overshoot",
    "buyback_ts",
    "not_bought_back",
    "restop",
    "missed_rebound",
)


def decide(runs: pd.DataFrame, stops: pd.DataFrame, grid: Grid) -> dict:
    """Section 6 from the runs and stops tables: the headline (Kraken 1x, A10/30d 'counts' against R), the
    robustness labels, and the descriptions (INTERPRETATIONS["descriptions"])."""
    head = pool_checks(runs, *HEADLINE_POOL)
    text = head["headline"]
    robustness = {}
    for source, cost in ROBUSTNESS_POOLS:
        ch = pool_checks(runs, source, cost)
        robustness[_name(source, cost)] = {**ch, "label": SAME if ch["headline"] == text else DIFFERS}
    pools = (HEADLINE_POOL, *ROBUSTNESS_POOLS)
    per_mix = {_name(*p): {_mix_name(m): pool_checks(runs, *p, mix=m) for m in grid.mixes} for p in pools}
    by_setting = {
        setting: {_name(*p): pool_checks(runs, *p, setting=setting) for p in pools}
        for setting in grid.settings
        if setting != REF
    }
    full = runs[runs["window"].to_numpy() == FULL]
    cand_stops = stops[stops["setting"].to_numpy() == CANDIDATE]
    stop_lists = {
        _name(*p): R.jsonable(
            cand_stops[(cand_stops["source"].to_numpy() == p[0]) & (cand_stops["cost"].to_numpy() == p[1])][
                list(STOP_SUMMARY)
            ].to_dict("records")
        )
        for p in pools
    }
    return {
        "verdict": head["verdict"],
        "whipsaw": head["V-c"],
        "headline": text,
        "checks": head,
        "robustness": robustness,
        "per_mix": per_mix,
        "settings": by_setting,
        "full_span": R.jsonable(full[list(FULL_SPAN_COLUMNS)].to_dict("records")),
        "stops": stop_lists,
    }


# ------------------------------------------------------------------------------------------------ the look


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=None, help="results folder (default results/protect-gains)")
    ap.add_argument("--catalog-dir", default=None, help="default data/catalog")
    ap.add_argument(
        "--config-dir", default=None, help="folder with costs.yaml, splits.yaml, risk_levels.yaml"
    )
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED", help="dry run on synthetic bars")
    return ap.parse_args(argv)


def make_context(
    grid: Grid, panels: Mapping[str, pd.DataFrame], limits: Mapping, costs: Mapping, snapshot_id, commit
) -> dict:
    """What :func:`block` reads: the grid, the windows, the panels, the index of each source and f over its whole
    panel (INTERPRETATIONS["index"]), the limits, the cost models and the record keys."""
    return {
        "grid": grid,
        "windows": {label: (a, z) for label, a, z in windows()},
        "panels": panels,
        "signals": {
            (source, f): P.index_signal(panels[source], f)
            for source in grid.sources
            for f in sorted({f for _, f in grid.mixes})
        },
        "limits": {"min_cash": limits["min_cash"], "max_coin": limits["max_coin"]},
        "costs": costs,
        "snapshot_id": snapshot_id,
        "commit": commit,
    }


def _tables(acc: Mapping) -> tuple[pd.DataFrame, pd.DataFrame]:
    return frame(acc["runs"], RUN_COLUMNS), frame(acc["stops"], STOP_TABLE_COLUMNS)


def study(args, g: dict, start: dict, acc: dict) -> dict:
    """From the snapshot pins to the tables and the checks (start.json is rewritten with the panels before any
    check; runs.parquet and stops.parquet are written before the count and the checks)."""
    look_dir = g["look_dir"]
    check_snapshot(g["snapshot"], g["synthetic"])
    loader = synthetic_bar_loader(args.synthetic) if g["synthetic"] else None
    panels = {
        source: load_look_panel(
            source, catalog_dir=g["catalog_dir"], config_dir=g["config_dir"], loader=loader
        )
        for source in SOURCES
    }
    start["panels"] = {s: {**R.panel_record(panels[s]), **data_record(panels[s])} for s in SOURCES}
    R.write_json(look_dir / "start.json", start)
    for source in SOURCES:
        check_panel(source, panels[source], g["synthetic"])
    grid = PLAN_GRID
    ctx = make_context(
        grid, panels, g["limits"], g["costs"], g["snapshot"]["snapshot_id"], g["git"]["commit"]
    )
    t = time.time()
    for source in grid.sources:
        for cost in grid.costs:
            for window in grid.windows:
                b = block(ctx, source, cost, window)
                for name in ("runs", "stops", "failures"):
                    acc[name] += b[name]
    runs, stops = _tables(acc)
    R.write_parquet(runs, look_dir / "runs.parquet")
    R.write_parquet(stops, look_dir / "stops.parquet")
    counts = check_count(runs, grid)
    decided = decide(runs, stops, grid)
    look = {
        "label": LABEL,
        "study": R.STUDY,
        "look": LOOK,
        "data": g["data"],
        "outcome": decided["verdict"],
        **decided,
        "thresholds": thresholds(),
        "counts": counts,
        "failed_runs": acc["failures"],
        "grid_runtime_s": time.time() - t,
        "start": {k: start[k] for k in ("commit", "config_hash", "plan_sha256", "snapshot", "utc")},
        "panels": start["panels"],
    }
    return {"runs": runs, "look": look}


def runs_csv(runs: pd.DataFrame) -> pd.DataFrame:
    """The tracked ``validate_runs.csv``: one row per run, :data:`CSV_COLUMNS` (no Sharpe or return column)."""
    return runs.reindex(columns=list(CSV_COLUMNS))


def write_look(g: Mapping, look: Mapping) -> None:
    """``look.json`` and its byte-identical tracked copy ``validate_look.json``."""
    text = R.json_text(look)
    R.write_text(g["look_dir"] / "look.json", text)
    R.write_text(g["tracked"] / "validate_look.json", text)


def spend(g: Mapping, start: Mapping, acc: Mapping, error: Mapping, event: str) -> None:
    """A stop or crash after STARTED: the look is spent (INCONCLUSIVE), recorded, and the runs so far are kept."""
    write_look(
        g,
        {
            "label": LABEL,
            "study": R.STUDY,
            "look": LOOK,
            "data": g["data"],
            "outcome": INCONCLUSIVE,
            "verdict": INCONCLUSIVE,
            "headline": INCONCLUSIVE,
            "error": error,
            "runs_logged": len(acc["runs"]),
            "failed_runs": acc["failures"],
            "start": {k: start[k] for k in ("commit", "config_hash", "plan_sha256", "snapshot", "utc")},
        },
    )
    R.append_runlog(
        g["log"],
        {"utc": R.utc_now(), "script": SCRIPT, "look": LOOK, "data": g["data"], "event": f"{EVENT}: {event}"},
    )
    if acc["runs"]:
        runs, stops = _tables(acc)
        R.write_parquet(runs, g["look_dir"] / "runs.parquet")
        R.write_parquet(stops, g["look_dir"] / "stops.parquet")


def run(args) -> int:
    g = start_guards(args)
    look_dir = g["look_dir"]
    look_dir.mkdir(parents=True)
    utc = R.utc_now()
    R.write_text(look_dir / "STARTED", f"{utc}\n")
    start = {
        "utc": utc,
        "script": SCRIPT,
        "study": R.STUDY,
        "look": LOOK,
        "event": EVENT,
        "data": g["data"],
        "synthetic_seed": args.synthetic,
        "git": g["git"],
        "commit": g["git"]["commit"],
        "config_hash": config_hash(g["hashes"]),
        "file_hashes": g["hashes"],
        "plan_sha256": g["plan_sha256"],
        "snapshot": g["snapshot"],
        "risk_limits": g["limits"],
        "costs": {name: asdict(c) for name, c in g["costs"].items()},
        "grid": {**asdict(PLAN_GRID), "counts": expected_count(PLAN_GRID)},
        "windows": windows(),
        "settings": SETTINGS,
        "thresholds": thresholds(),
        "out_dir": str(g["out"]),
        "config_dir": None if g["config_dir"] is None else str(g["config_dir"]),
        "catalog_dir": str(g["catalog_dir"]),
        "interpretations": INTERPRETATIONS,
        "label": LABEL,
    }
    R.write_json(look_dir / "start.json", start)
    R.append_runlog(
        g["log"],
        {
            "utc": utc,
            "script": SCRIPT,
            "event": EVENT,
            "look": LOOK,
            "commit": g["git"]["commit"],
            "dirty": g["git"]["dirty"],
            "config_hash": start["config_hash"],
            "plan_sha256": g["plan_sha256"],
            "snapshot_id": g["snapshot"]["snapshot_id"],
            "data": g["data"],
            "out_dir": str(g["out"]),
        },
    )
    print(f"validate look {LOOK} ({g['data']}) started; config hash {start['config_hash'][:16]}", flush=True)
    acc: dict = {"runs": [], "stops": [], "failures": []}
    try:
        result = study(args, g, start, acc)
        if file_hashes(g["config_dir"]) != g["hashes"]:
            raise Stop("consistency", "a hashed file changed during the look")
        write_look(g, result["look"])
        R.write_text(g["tracked"] / "validate_runs.csv", R.csv_text(runs_csv(result["runs"])))
    except Stop as exc:
        spend(g, start, acc, {"kind": exc.kind, "message": str(exc)}, f"{INCONCLUSIVE} (stopped)")
        print(f"STOP: {exc}. The look is spent (INCONCLUSIVE)", file=sys.stderr)
        return 3
    except Exception as exc:
        error = {
            "kind": "crash",
            "message": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        spend(g, start, acc, error, f"{INCONCLUSIVE} (crashed)")
        raise
    look = result["look"]
    R.append_runlog(
        g["log"],
        {
            "utc": R.utc_now(),
            "script": SCRIPT,
            "look": LOOK,
            "data": g["data"],
            "event": f"{EVENT}: complete",
            "outcome": look["outcome"],
            "headline": look["headline"],
        },
    )
    print(
        f"validate look {LOOK} complete: {look['headline']} ({look['counts']['got']['total']} runs)",
        flush=True,
    )
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
