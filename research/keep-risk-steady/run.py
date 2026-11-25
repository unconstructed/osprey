"""keep-risk-steady: the study's one script (``research/keep-risk-steady/PLAN.md`` sections 3-15; section numbers below
are that file's).

SCOUTING ONLY. Every number comes from the reference portfolio engine (``lab.runner.portfolio``, driven by
``lab.runner.keeprisk``), not NautilusTrader (AGENTS.md hard rule 3), with the PLACEHOLDER costs of
``config/costs.yaml`` and exchange candles standing in for Base prices. It claims no return edge and approves nothing.
It reads the train years only: every panel comes from ``lab.data.panel.load_panel`` with ``last_close`` = 2023-01-01
00:00 UTC (the last train close); validate and test stay unread.

    uv run python research/keep-risk-steady/run.py                                  # run 0 on real data (2 workers)
    uv run python research/keep-risk-steady/run.py --amendment 1                    # amendment run 1 (stop rule 6)
    uv run python research/keep-risk-steady/run.py --synthetic 7 --fast --out-dir <scratch>   # dry run
    uv run python research/keep-risk-steady/run.py --time --out-dir <scratch>       # the A1 timing only

Start guards, all before anything is written (exit 2): a real run uses the pinned folders only (``--out-dir``
results/keep-risk-steady, ``--config-dir`` unset or config/, ``--catalog-dir`` data/catalog) and a dry run never writes
into results/keep-risk-steady or anywhere in the repo; ``--fast`` is for dry runs only; run 0 refuses an earlier run
folder and ``--amendment k`` refuses unless 1 <= k <= 2, ``run<k-1>/start.json`` exists, ``run<k>/`` does not, every
earlier run is the same kind of run and (real data) PLAN.md section 13's amendments list holds ``- **Amendment run k``;
the RUNLOG must not hold this run number; a real run refuses a dirty git tree, a plan without exactly one A1 and one A0
record (stop rule 8; the A0 item holding the pinned phrase "A0 alarms: none" or naming an owner decision on file,
and an A0 item that reports an alarm refused unless it names an owner decision on file: stop rule 9) and a catalog
whose bars hash is not the pinned one; ``risk_limits("steady")`` must give exactly min_cash 0.20 and max_coin 0.60
(section 4) and every target of the grid must pass ``check_targets`` with them and h = 0.02; a real run whose
projection (the A1 timing, made again at start) is above 240 CPU-minutes does not start (stop rule 7).

Then, before any bar is read: ``run<k>/start.json`` and one RUNLOG line. Then the panels (row counts, panel hashes on
real data, every calendar window present: stop rule 2; a close after 2023-01-01: stop rule 3), BTC's calendar-year
returns on Kraken (the boom ranking, written before any backtest), the swing and its independent numpy recompute
(section 11), the blocks (window blocks and full-span cells) in worker processes, each block's tables written to
``run<k>/blocks/`` as it returns, the tables (written before any count or decision), the counts, the cross-run checks
of section 11, the resampling, the labels, D1-D3 and the outputs: ``runs.parquet``, ``series.parquet``,
``failures.parquet``, ``spans.parquet``, ``summary.json`` and ``decision.json`` in ``run<k>/``; the tracked
``RUNLOG.jsonl``, ``runs.csv``, ``spans.csv`` and ``decision.json`` in this folder (dry runs: ``<out>/tracked/``).
Exit codes: 0 done, 2 refused at start, 3 stopped.

The computations live in tested code, ``lab/runner/keeprisk.py``. This file holds the pinned values, the guards, the
grid's bookkeeping and the outputs. ``research/`` is never imported by ``lab/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import platform
import re
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.external import HoldoutWindowError
from lab.data.panel import instruments, load_panel
from lab.data.synthetic import synthetic_market
from lab.runner import holdmix as H
from lab.runner import keeprisk as K
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner import trend as T
from lab.runner.reference import Costs
from lab.runner.steady import panel_hash

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
SCRIPT = "run.py"
STUDY = "keep-risk-steady"
DEFAULT_OUT = REPO / "results" / STUDY
DEFAULT_CATALOG = REPO / "data" / "catalog"

INTERVAL = "1d"
LAST_CLOSE = H.LAST_CLOSE  # 2023-01-01 00:00 UTC, the last train close (section 3)
SNAPSHOT_ID = "1746a21b75683e76"  # section 3 (recorded; the hashes decide)
BARS_SHA256 = "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"
PANEL_HASHES = {
    "KRAKEN": "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
    "BINANCE": "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
}
ROWS = {"KRAKEN": 2190, "BINANCE": 1963}
MAX_AMENDMENTS = 2  # stop rule 6
CPU_MINUTES_MAX = 240.0  # stop rule 7: run 0
A0_CPU_MINUTES_MAX = 300.0  # stop rule 7: A0 (the owner's limit, 2026-11-25)
TIMING_REPS = 3
TIMING_REPS_FAST = 1
TIMING_PANEL = 399999  # A1: trend.garch_panel(399999)
TIMING_CELL = (0.08, 0.60, 0.50)  # A1: the busiest cell (w, s, f)
TIMING_WINDOW = 24  # a 24-month window of the Kraken grid
STRESS = 2.0
CONFIG_FILES = ("config/costs.yaml", "config/splits.yaml", "config/risk_levels.yaml")
BOOK_CHECK_EVERY = 9  # section 11
SIGMA_RTOL = 1e-12  # section 11: the numpy recompute of sigma
LABEL = K.LABEL
OWNER_DECISION_RE = re.compile(r"owner decision: `?(?P<path>reports/director/[\w.-]+\.md)")
# a mention of an owner decision that says there is none ('no owner decision: ...', 'awaiting the owner decision: ...')
OWNER_DECISION_NEGATED_RE = re.compile(
    r"\b(?:no|not|without|pending|awaiting)\W+(?:(?:an?|the|any)\W+)?$", re.IGNORECASE
)
A0_NO_ALARM = "A0 alarms: none"  # stop rule 8: the pinned phrase of an A0 record with no alarm
A0_NO_ALARM_RE = re.compile(rf"(?<!\w){re.escape(A0_NO_ALARM)}(?!\w)")
A0_FIRED_RE = re.compile(r"fired", re.IGNORECASE)  # stop rule 9: an A0 record that reports an alarm ...
_A0_NAME = r"A0\W?\d(?!\d)"  # an alarm's name: A0-3, A0 3, A0–3
A0_ALARM_RE = re.compile(  # ... or names one outside the pinned phrase (INTERPRETATIONS["prior_amendments"])
    rf"\balarms?\b\W{{0,4}}(?:(?:on|for|at|in|from|of|by)\W{{1,4}})?{_A0_NAME}"
    rf"|{_A0_NAME}(?:\W{{1,4}}\w+){{0,6}}?\W{{1,4}}(?:alarms?|fire|fires|firing|trigger\w*|trip|trips|tripped|"
    r"tripping|exceed\w*|breach\w*|raised|(?:over|above|past|beyond)\W+(?:its|the)\W+limit)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Family:
    """A family of runs (section 7): one source, cost level, look-back and wallet size."""

    name: str
    source: str
    cost: str
    lookback: int
    wallet: float
    copies: bool  # the full spans run the guarded copies (E1) and get labels
    decisive: bool  # a pool of D1 and D2 (Kraken 1x, Binance 1x, Kraken 2x)


FAMILIES = (
    Family("KRAKEN 1x", "KRAKEN", "1x", 14, K.DEPOSIT, True, True),
    Family("BINANCE 1x", "BINANCE", "1x", 14, K.DEPOSIT, True, True),
    Family("KRAKEN 2x", "KRAKEN", "2x", 14, K.DEPOSIT, True, True),
    Family("KRAKEN 1x L7", "KRAKEN", "1x", 7, K.DEPOSIT, True, False),
    Family("KRAKEN 1x L28", "KRAKEN", "1x", 28, K.DEPOSIT, True, False),
    Family("KRAKEN 1x 500 USD", "KRAKEN", "1x", 14, K.SMALL_DEPOSIT, False, False),
)
FAMILY = {fam.name: fam for fam in FAMILIES}
HEADLINE = "KRAKEN 1x"
CHECK_FAMILIES = {"Binance": "BINANCE 1x", "2x costs": "KRAKEN 2x"}
# W: the Monday checks c >= L of each panel grid (section 5.5), from the calendar (tested by hand)
CHECKS = {("KRAKEN", 14): 311, ("KRAKEN", 7): 312, ("KRAKEN", 28): 309, ("BINANCE", 14): 278}
ALL = "all"
LOYO = tuple(f"without {y}" for y in H.TRAIN_YEARS)
BOOM = ("without the best 1", "without the best 2")

INTERPRETATIONS = {
    **{f"keeprisk.{k}": v for k, v in K.READINGS_PINNED.items()},
    "fast": "--fast is a small dry-run grid: the four w, mixes (0.50, 0.50) and (0.60, 0.75), Kraken windows 0, 24, "
    "48 and Binance 8, 48, every family, every 64th guarded copy and 500 resamples. The rules run on it "
    "mechanically (E1 cannot hold with 5 copies; a boom check leaves fewer than 12 windows, so it is MISSING)",
    "families": "Section 7's pools and descriptions as families: Kraken 1x, Binance 1x and Kraken 2x at 14 returns "
    "and 5,000 USD (the pools of D1 and D2), Kraken 1x at 7 and 28 returns (with copies and labels) and Kraken 1x "
    "at 500 USD (no copies and no label: its full span gets V and the p-values of RISK-X only)",
    "x_eq_not_run": "An X_eq whose V is MISSING is not run; it is logged with status 'not run' (section 6: "
    "'recorded'), counted in section 7's counts, and never makes a pool MISSING",
    "copy0": "Copy u = 0 is run in every full span with copies as a check (its targets and its run equal the "
    "rule's bit for bit: returns, weights, orders, reasons and targets); it is not one of section 7's counted runs",
    "rowsets": "Kraken 1x's full spans are also measured without each bar-year (2017 .. 2022) and without BTC's best "
    "bar-year and its two best (protect.boom_removals on holdmix.year_returns of Kraken's closes, ties to the "
    "earlier year): V, every V_u and RISK-X on the kept return rows, each removal its own index set (seed 0); the "
    "same runs, nothing refitted. Ten index sets in all (Kraken all, Binance all, six years, two boom removals)",
    "boom": "D2's boom checks rerun D1 on the Kraken 1x windows overlapping none of the removed years "
    "(protect.windows_without; fewer than 12 gives MISSING) with the labels of the matching rowset",
    "steps_check": "Section 11's 'the steps do not depend on costs, the wallet or s': for each source, look-back, "
    "f, w and window (or full span), every rule run's q path (keeprisk.q_hash) and step-order closes "
    "(keeprisk.step_hash) are equal across s, cost levels and wallet sizes, else stop rule 5; the pairs whose "
    "orders differ (drift and limit orders read the wallet) are counted",
    "sigma_check": "Section 11's recompute: at every decision row (each Monday c >= L and each window's first row "
    "r0 >= L) of each source, f and look-back, numpy's std(ddof=1) x sqrt(365) over the same L returns agrees "
    "with the engine's sigma to 1e-12 relative, and its q is the engine's for every w, except where 4 tau / sigma "
    "is within 1e-9 of a whole number (listed in summary.json)",
    "window_check": "Each window's closes are exactly its calendar days (holdmix.window_slice: 729-731 rows, Kraken's "
    "2018-01-13 the one pinned missing close), and its q from its first Monday check on equals the full panel's q "
    "on those closes",
    "time": "A1 (--time, and again at a real run's start): on trend.garch_panel(399999) relabelled as a synthetic "
    "panel, the busiest cell (w 8%, s 0.60, f 0.50): a full-span rule run, a guarded copy with its mix, a window run "
    "of each kind (window 24), one index set of 10,000 and one RISK-X, each with every check; the medians times "
    "section 7's counts project run 0 (every full-span run charged at the rule's time) and A0 (500 panels)",
    "dirty": "A dirty git tree (git status --porcelain --untracked-files=all prints anything) refuses real runs only",
    "run0": "A real run 0 refuses when results/keep-risk-steady/ exists; a dry run 0 refuses when <out>/run<j>/ "
    "exists",
    "same_kind_of_run": "--amendment k refuses unless every earlier run has the same data and --fast setting",
    "runlog": "A run number the RUNLOG already holds for the same data (any line) is refused. Besides the start "
    "line, an event line is appended when a run completes, stops or crashes",
    "prior_amendments": "Stop rule 8: section 13's amendments list (from '**Amendments:**' to '## 14.') must hold "
    "exactly one item starting '- **A1' or '- **Amendment A1' at a line's start and one for A0. An item is its first "
    "line and every indented line after it (blank lines inside it included) up to the next line that starts at the "
    "line's start; only the A0 item is read, never the plan's other text. Neither item may hold 'to be written' (the "
    "committed placeholders). The A0 item must hold the pinned phrase 'A0 alarms: none' (exactly, case included, as "
    "whole words, on one line; 'no alarm' alone is not it) or name an owner decision, 'owner decision: "
    "reports/director/<file>.md'; every decision it names must exist, and a mention that says there is none ('no', "
    "'not', 'without', 'pending' or 'awaiting', optionally with 'a', 'an', 'the' or 'any', just before it) names no "
    "decision. Stop rule 9: an A0 item that reports an alarm is refused unless it names an owner decision on file, "
    "whatever else it says. It reports one when it holds the word 'fired' anywhere (any case, inside a longer word "
    "too), or, outside the pinned phrase and in any case, 'alarm' or 'alarms' followed by an alarm's name (A0-<n>, A0 "
    "<n> or A0<n>) with at most 4 characters other than letters, digits and '_' between them, or with 'on', 'for', "
    "'at', 'in', 'from', 'of' or 'by' between them ('alarms: A0-3', 'alarm (A0-3)', 'alarm **A0-3**', 'alarm on "
    "A0-3'), or an alarm's name followed within 6 words (at most 4 such characters between words) by 'alarm(s)', "
    "'fire(s)', 'firing', 'trigger...', 'trip(s/ped/ping)', 'exceed...', 'breach...', 'raised' or 'over/above/past/"
    "beyond its/the limit' ('A0-3 triggered', 'A0 3 alarm', 'A0-3 at 14 of 100, over its limit'). Real runs only",
    "snapshot": "Section 3's snapshot id is recorded with the catalog's; the bars hash and the panel hashes decide",
    "limits": "risk_limits('steady') must give min_cash exactly 0.20 and max_coin exactly 0.60 (section 4), and "
    "every target of the grid (s q f, s q (1 - f)) must pass check_targets with them and h = 0.02",
    "stop_rule_3": "The loader is wrapped: a close after 2023-01-01 00:00 UTC stops the run before load_panel sees it "
    "(a tz-naive index read as UTC); recorded in summary.json and the RUNLOG",
    "failures": "A run that raises (other than a consistency stop) is logged as failed with its error text and "
    "traceback, and the grid goes on; every decision that needs its pool is MISSING (stop rule 4)",
    "consistency": "Stop rule 5 in each run: every order's targets through check_targets; the yardsticks' reasons "
    "and targets (keeprisk.check_yardstick) with x recomputed here by an independent exact mean; copy 0 against "
    "the rule; every copy's multiset of check q's against the rule's; the window check; the book of coin units and "
    "cash (protect.check_book) on every 9th run of a block; every run's fee check (holdmix.money_metrics); then the "
    "counts, the steps check and every hashed file hashed again",
    "csv": "runs.csv: one row per window run of every family (section 15's columns; no Sharpe column); spans.csv: one "
    "row per family, rowset and cell (V, its interval, p_calm and Holm, p_rough, p_eq, E1's rank p, the label, the "
    "cost flag)",
    "parallel": "Workers are forked processes; rows are sorted by a pinned key, so the outputs do not depend on the "
    "number of workers",
    "logging": "Each block's tables (runs, series, failures) are written to run<k>/blocks/ as soon as the block "
    "returns, so a stop, a crash or a killed process keeps every block computed so far; with 2 workers, blocks "
    "already running when another block stops finish and are written too",
    "year": "D3's year of a window is the calendar year of its first close",
}


class Refusal(Exception):
    """A start guard refused: nothing was run (exit code 2)."""


class Stop(Exception):
    """A stop rule fired after the start (exit code 3)."""

    def __init__(self, rule: str, message: str):
        super().__init__(f"stop rule {rule}: {message}")
        self.rule = rule


# ------------------------------------------------------------------------------------------------ the grid


def _all_windows(source: str) -> tuple[int, ...]:
    return tuple(k for k, _, _ in P.rolling_windows(source))


@dataclass(frozen=True)
class Grid:
    """What a run covers: the settings w, the mixes (s, f), the windows per source, the families, every
    ``copy_stride``-th guarded copy and the resamples."""

    settings: tuple[float, ...]
    mixes: tuple[tuple[float, float], ...]
    windows: Mapping[str, tuple[int, ...]]
    families: tuple[str, ...] = tuple(fam.name for fam in FAMILIES)
    copy_stride: int = 1
    resamples: int = K.RESAMPLES
    name: str = "plan"

    def offsets(self, source: str, lookback: int) -> np.ndarray:
        return T.guarded_offsets(CHECKS[(source, lookback)])[:: self.copy_stride]

    def record(self) -> dict:
        return jsonable({**asdict(self), "counts": expected_counts(self)})


PLAN_GRID = Grid(settings=K.W_VALUES, mixes=K.MIXES, windows={s: _all_windows(s) for s in H.SOURCES})
FAST = Grid(
    settings=K.W_VALUES,
    mixes=((0.50, 0.50), (0.60, 0.75)),
    windows={"KRAKEN": (0, 24, 48), "BINANCE": (8, 48)},
    copy_stride=64,
    resamples=500,
    name="fast",
)


def expected_counts(grid: Grid) -> dict:
    """Section 7's counts for ``grid``: per family, 4 window runs per cell and window, and per cell 4 full-span runs
    plus a copy and its mix per guarded offset (families with copies). The plan's grid: 117,760."""
    cells = len(grid.settings) * len(grid.mixes)
    out, total = {}, 0
    for name in grid.families:
        fam = FAMILY[name]
        windows = len(grid.windows[fam.source]) * cells * len(K.KINDS)
        copies = len(grid.offsets(fam.source, fam.lookback)) if fam.copies else 0
        spans = cells * (len(K.KINDS) + 2 * copies)
        out[name] = {"windows": windows, "spans": spans, "copies_per_cell": copies}
        total += windows + spans
    return {"families": out, "total": total}


def tasks(grid: Grid) -> list[tuple]:
    """The blocks, in order: each family's window blocks, then its full-span cells."""
    out = []
    for name in grid.families:
        fam = FAMILY[name]
        out += [("window", name, k) for k in grid.windows[fam.source]]
        out += [("span", name, w, s, f) for w in grid.settings for s, f in grid.mixes]
    return out


def thresholds() -> dict:
    return {
        "ALPHA": K.ALPHA,
        "DELTA": K.DELTA,
        "COST_MARGIN": K.COST_MARGIN,
        "COST_MARGIN_POINTS": K.COST_MARGIN_POINTS,
        "BAND": K.BAND,
        "LOOKBACK": K.LOOKBACK,
        "MEAN_BLOCK": K.MEAN_BLOCK,
        "RESAMPLES": K.RESAMPLES,
        "LEAD_GUARD": K.LEAD_GUARD,
        "HOLM": "p_(j) < 0.05 / (5 - j) for every j <= i (strict)",
        "D1_RULE_1": "2 x calmer windows >= windows",
        "BOOM_MIN_WINDOWS": K.BOOM_MIN_WINDOWS,
        "REBOUND_DAYS": K.REBOUND_DAYS,
    }


def pinned_values() -> dict:
    """The pinned values of the config hash."""
    return jsonable(
        {
            "grid": asdict(PLAN_GRID),
            "families": [asdict(fam) for fam in FAMILIES],
            "checks": {f"{s} {lb}": w for (s, lb), w in CHECKS.items()},
            "windows": {s: P.rolling_windows(s) for s in H.SOURCES},
            "missing_closes": H.MISSING_CLOSES,
            "limits": {"min_cash": K.STEADY_MIN_CASH, "max_coin": K.STEADY_MAX_COIN},
            "thresholds": thresholds(),
            "stress": STRESS,
            "snapshot_id": SNAPSHOT_ID,
            "bars_sha256": BARS_SHA256,
            "panel_hashes": PANEL_HASHES,
            "rows": ROWS,
            "last_close": LAST_CLOSE,
            "book_check_every": BOOK_CHECK_EVERY,
            "cpu_minutes": {"run0": CPU_MINUTES_MAX, "a0": A0_CPU_MINUTES_MAX},
            "timing": {"panel": TIMING_PANEL, "cell": TIMING_CELL, "window": TIMING_WINDOW},
            "readings": INTERPRETATIONS,
        }
    )


# ------------------------------------------------------------------------------------- hashing, git, json


def frozen_paths() -> list[str]:
    """The repo-relative files of the config hash (section 11), sorted."""
    validation = {p.relative_to(REPO).as_posix() for p in (REPO / "lab" / "validation").glob("*.py")}
    return sorted(
        validation
        | {
            "research/keep-risk-steady/PLAN.md",
            "research/keep-risk-steady/run.py",
            "research/keep-risk-steady/controls.py",
            "lab/runner/keeprisk.py",
            "lab/runner/volsteady.py",
            "lab/runner/trend.py",
            "lab/runner/protect.py",
            "lab/runner/holdmix.py",
            "lab/runner/portfolio.py",
            "lab/runner/reference.py",
            "lab/runner/steady.py",
            "lab/runner/interface.py",
            "lab/data/panel.py",
            "lab/data/catalog.py",
            "lab/data/external.py",
            "lab/data/loaders.py",
            "lab/config.py",
            *CONFIG_FILES,
            "pyproject.toml",
            "uv.lock",
        }
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hashes(config_dir: Path | None = None) -> dict[str, str]:
    cfg = Path(config_dir) if config_dir is not None else CONFIG_DIR
    return {
        rel: sha256_file(cfg / Path(rel).name if rel in CONFIG_FILES else REPO / rel)
        for rel in frozen_paths()
    }


def config_hash(hashes: Mapping[str, str]) -> str:
    blob = json.dumps({"files": dict(sorted(hashes.items())), "pinned": pinned_values()}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def git_state(repo: Path = REPO) -> dict:
    def run(*args: str) -> str:
        res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {res.stderr.strip()}")
        return res.stdout

    commit = run("rev-parse", "HEAD").strip()
    changes = [line for line in run("status", "--porcelain", "--untracked-files=all").splitlines() if line]
    return {"commit": commit, "dirty": bool(changes), "changes": changes[:50]}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def jsonable(x):
    """Plain JSON types: numpy scalars and arrays, timestamps, tuples; NaN, inf and NaT become None."""
    if isinstance(x, Mapping):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, np.bool_ | bool):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, float | np.floating):
        return float(x) if math.isfinite(float(x)) else None
    if x is pd.NaT:
        return None
    if isinstance(x, pd.Timestamp | np.datetime64):
        ts = pd.Timestamp(x)
        return None if pd.isna(ts) else ts.isoformat()
    return x


def json_text(obj) -> str:
    return json.dumps(jsonable(obj), indent=1, sort_keys=True) + "\n"


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_json(path: Path, obj) -> None:
    write_text(path, json_text(obj))


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def append_runlog(path: Path, entry: Mapping) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(jsonable(entry), sort_keys=True) + "\n")


def runlog_entries(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def tracked_dir(out: Path, synthetic: bool) -> Path:
    return Path(out) / "tracked" if synthetic else HERE


def runlog_path(out: Path, synthetic: bool) -> Path:
    return tracked_dir(out, synthetic) / "RUNLOG.jsonl"


def amendments_list(plan_text: str) -> str | None:
    """Section 13's amendments list: from the line starting ``**Amendments:**`` to the heading ``## 14.``."""
    start = re.search(r"^\*\*Amendments:?\*\*", plan_text, re.MULTILINE)
    end = re.search(r"^## 14\.", plan_text, re.MULTILINE)
    if start is None or end is None or end.start() < start.start():
        return None
    return plan_text[start.start() : end.start()]


def amendment_row_present(plan_text: str, k: int) -> bool:
    section = amendments_list(plan_text)
    return section is not None and bool(re.search(rf"^- \*\*Amendment run {k}\b", section, re.MULTILINE))


def amendment_items(section: str, name: str) -> list[str]:
    """The items of the amendments list that record ``name`` (INTERPRETATIONS["prior_amendments"]): each line starting
    ``- **<name>`` or ``- **Amendment <name>`` at the line's start, with every indented line after it (blank lines
    inside the item included) up to the next line that starts at the line's start."""
    lines = section.splitlines()
    out = []
    for i, line in enumerate(lines):
        if re.match(rf"- \*\*(?:Amendment )?{name}\b", line):
            item = [line]
            for later in lines[i + 1 :]:
                if later.strip() and not later[:1].isspace():
                    break
                item.append(later)
            out.append("\n".join(item).rstrip())
    return out


def prior_amendments(plan_text: str, repo: Path = REPO) -> dict:
    """Stop rule 8 (INTERPRETATIONS["prior_amendments"]): exactly one A1 and one A0 record before a real run."""
    section = amendments_list(plan_text)
    if section is None:
        raise Refusal("PLAN.md section 13 has no amendments list ('**Amendments:**' .. '## 14.')")
    rows = {name: amendment_items(section, name) for name in ("A1", "A0")}
    for name in ("A1", "A0"):
        if len(rows[name]) != 1 or "to be written" in rows[name][0]:
            raise Refusal(
                f"stop rule 8: PLAN.md section 13 needs exactly one '- **{name}' record (not the placeholder) before "
                f"a real run; found {len(rows[name])} line(s)"
            )
    a0 = rows["A0"][0]
    decisions = owner_decisions(a0)
    for path in decisions:
        if not (Path(repo) / path).is_file():
            raise Refusal(f"amendment A0 names an owner decision {path} that does not exist")
    decision = decisions[0] if decisions else None
    alarm = a0_alarm(a0)
    if decision is None and alarm is not None:
        raise Refusal(
            f"stop rule 9: amendment A0 reports an alarm ({alarm!r}) and names no owner decision on file "
            "('owner decision: reports/director/<file>.md'): run 0 does not start"
        )
    if decision is None and A0_NO_ALARM_RE.search(a0) is None:
        raise Refusal(
            f"stop rule 8: amendment A0 says neither '{A0_NO_ALARM}' nor 'owner decision: "
            "reports/director/<file>.md'"
        )
    return {"A1": rows["A1"][0], "A0": a0, "alarm": alarm, "owner_decision": decision}


def owner_decisions(record: str) -> list[str]:
    """Every owner decision an A0 record names, in order; a mention that says there is none is not one
    (INTERPRETATIONS["prior_amendments"])."""
    return [
        m["path"]
        for m in OWNER_DECISION_RE.finditer(record)
        if OWNER_DECISION_NEGATED_RE.search(record[: m.start()]) is None
    ]


def a0_alarm(record: str) -> str | None:
    """The text by which an A0 record reports an alarm (INTERPRETATIONS["prior_amendments"]), or None: the word
    'fired' anywhere, or an alarm named next to 'alarm' or an alarm word outside the pinned phrase."""
    fired = A0_FIRED_RE.search(record)
    if fired is not None:
        return fired.group(0)
    named = A0_ALARM_RE.search(A0_NO_ALARM_RE.sub(" ", record))
    return None if named is None else named.group(0)


# ------------------------------------------------------------------------------------------- start guards


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path) -> None:
    """A dry run (or the timing, or A0) never writes into results/keep-risk-steady or anywhere in the repo."""
    where = Path(out).resolve()
    if _inside(where, DEFAULT_OUT.resolve()) or _inside(where, REPO.resolve()):
        raise Refusal(
            f"--out-dir {out}: a synthetic dry run never writes into {DEFAULT_OUT} or inside the repo; use a "
            "scratch folder"
        )


def check_real_paths(out: Path, config_dir: Path | None, catalog_dir: Path) -> None:
    if Path(out).resolve() != DEFAULT_OUT.resolve():
        raise Refusal(f"--out-dir {out}: a real run writes only to {DEFAULT_OUT}")
    if config_dir is not None and Path(config_dir).resolve() != (REPO / "config").resolve():
        raise Refusal(f"--config-dir {config_dir}: a real run reads config/ only")
    if Path(catalog_dir).resolve() != DEFAULT_CATALOG.resolve():
        raise Refusal(f"--catalog-dir {catalog_dir}: a real run reads only {DEFAULT_CATALOG} (section 3)")


def check_layout(out: Path, k: int, synthetic: bool) -> None:
    out = Path(out)
    if k == 0:
        if not synthetic and out.exists():
            raise Refusal(f"{out} exists: run 0 runs once (stop rule 6). A rerun is --amendment k")
        if out.is_dir() and any(re.fullmatch(r"run\d+", p.name) for p in out.iterdir()):
            raise Refusal(f"{out} already holds a run folder: run 0 runs once (stop rule 6)")
        return
    if not 1 <= k <= MAX_AMENDMENTS:
        raise Refusal(f"--amendment {k}: amendment runs are numbered 1..{MAX_AMENDMENTS} (stop rule 6)")
    if not (out / f"run{k - 1}" / "start.json").is_file():
        raise Refusal(f"--amendment {k}: {out / f'run{k - 1}' / 'start.json'} does not exist")
    if (out / f"run{k}").exists():
        raise Refusal(f"--amendment {k}: {out / f'run{k}'} exists (a run is never resumed: stop rule 6)")


def check_earlier_runs(out: Path, k: int, data: str, fast: bool) -> None:
    for j in range(k):
        path = Path(out) / f"run{j}" / "start.json"
        try:
            start = json.loads(path.read_text())
            seen = (start["data"], bool(start["fast"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Refusal(f"--amendment {k}: cannot read run {j}'s start record {path}: {exc!r}") from exc
        if seen != (data, fast):
            raise Refusal(
                f"--amendment {k}: run {j} was a {seen[0]} run (fast {seen[1]}); this one is {data} (fast {fast})"
            )


def check_runlog(path: Path, k: int, data: str) -> None:
    for line in runlog_entries(path):
        if line.get("script") == SCRIPT and line.get("run") == k and line.get("data") == data:
            raise Refusal(
                f"{path} already records {data} run {k} ({line.get('utc')}): a deleted run is not rerun under its "
                "number (stop rule 6)"
            )


def read_snapshot(catalog_dir: Path, synthetic: bool) -> dict:
    if synthetic:
        return {
            "snapshot_id": "synthetic",
            "bars_content_sha256": "synthetic",
            "plan_snapshot_id": SNAPSHOT_ID,
        }
    path = Path(catalog_dir) / catalog.SNAPSHOT_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read {path}: {exc}") from exc
    snap = {"snapshot_id": data.get("snapshot_id"), "bars_content_sha256": data.get("bars_content_sha256")}
    if snap["bars_content_sha256"] != BARS_SHA256:
        raise Refusal(
            f"the catalog's bars hash {snap['bars_content_sha256']!r} is not {BARS_SHA256} (section 3, stop rule 2)"
        )
    if not isinstance(snap["snapshot_id"], str) or not snap["snapshot_id"]:
        raise Refusal(f"{path} names no snapshot_id")
    snap["plan_snapshot_id"] = SNAPSHOT_ID
    return snap


def steady_limits(config_dir: Path | None) -> dict:
    """``portfolio.risk_limits("steady")``, refused unless min_cash is 0.20 and max_coin 0.60 as read (section 4)."""
    try:
        limits = pf.risk_limits("steady", config_dir)
    except (ValueError, OSError) as exc:
        raise Refusal(f"risk_limits('steady') does not read: {exc}") from exc
    got = (limits["min_cash"], limits["max_coin"])
    if got != (K.STEADY_MIN_CASH, K.STEADY_MAX_COIN):
        raise Refusal(
            f"the steady level's limits as read are min_cash {got[0]!r} and max_coin {got[1]!r}, not the plan's "
            f"{K.STEADY_MIN_CASH} and {K.STEADY_MAX_COIN} (section 4): amend the plan before any run"
        )
    return limits


QUARTERS = (1.0, 0.75, 0.5, 0.25, 0.0)


def check_grid_targets(mixes: Iterable, limits: Mapping) -> int:
    """Every target (s q f, s q (1 - f)) of the plan's mixes and the grid's, q in the quarters, passes
    ``check_targets`` with the limits as read and h = 0.02 (section 4). Returns the number checked."""
    n = 0
    try:
        for s, f in (*K.MIXES, *mixes):
            for w_btc, w_eth in K.rule_targets(QUARTERS, s, f).tolist():
                pf.check_targets(
                    w_btc,
                    w_eth,
                    min_cash=limits["min_cash"],
                    max_coin=limits["max_coin"],
                    headroom=K.HEADROOM,
                )
                n += 1
    except ValueError as exc:
        raise Refusal(f"the Steady limits as read refuse a target of the grid (section 4): {exc}") from exc
    return n


def cost_models(config_dir: Path | None) -> dict[tuple[str, float], Costs]:
    """``Costs.from_yaml(capital_usd=wallet)`` (1x) and its ``stressed(2.0)`` (2x), per wallet (section 3)."""
    path = None if config_dir is None else Path(config_dir) / "costs.yaml"
    out = {}
    for wallet in sorted({fam.wallet for fam in FAMILIES}):
        base = Costs.from_yaml(path, capital_usd=wallet)
        out[("1x", wallet)] = base
        out[("2x", wallet)] = base.stressed(STRESS)
    return out


# ------------------------------------------------------------------------------------------------ the data

SYNTHETIC_DAYS = 2191
SYNTHETIC_FIRST = "2017-01-02"


def synthetic_bar_loader(seed: int) -> Callable:
    """A stand-in for ``lab.data.catalog.load_bars`` serving SYNTHETIC daily bars on the plan's date grid (dry runs and
    tests only): Kraken from close 2017-01-02 with ETH's 2018-01-13 bar missing; Binance from 2017-08-18 (the same
    bars times a small per-bar factor). Snapshot id ``"synthetic"``."""
    ids = {inst: (src, asset) for src in H.SOURCES for asset, inst in instruments(src).items()}
    market: dict[str, pd.DataFrame] = {}

    def loader(instrument, interval, start=None, end=None, catalog_dir=None) -> pd.DataFrame:
        if interval != INTERVAL or instrument not in ids:
            raise ValueError(f"synthetic loader: no {instrument!r} {interval!r} bars")
        if not market:
            market.update(synthetic_market(SYNTHETIC_DAYS, seed=seed, start=SYNTHETIC_FIRST))
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


def guarded(loader: Callable | None) -> Callable:
    """The loader ``load_panel`` calls, wrapped: a close after 2023-01-01 00:00 UTC raises ``HoldoutWindowError``
    (stop rule 3) before ``load_panel`` sees the bars. ``None`` means ``lab.data.catalog.load_bars``."""

    def call(instrument, interval, start=None, end=None, catalog_dir=None):
        inner = catalog.load_bars if loader is None else loader
        frame = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
        index = getattr(frame, "index", None)
        if isinstance(index, pd.DatetimeIndex) and len(index):
            latest = index.max()
            latest = latest.tz_localize("UTC") if latest.tzinfo is None else latest
            if latest > LAST_CLOSE:
                raise HoldoutWindowError(
                    f"{instrument}: the loader returned a close {latest.isoformat()} after the last train close "
                    f"{LAST_CLOSE.isoformat()}"
                )
        return frame

    return call


def load_study_panel(source: str, *, catalog_dir: Path, config_dir: Path | None, loader: Callable | None):
    try:
        panel = load_panel(
            source,
            INTERVAL,
            last_close=LAST_CLOSE,
            catalog_dir=catalog_dir,
            config_dir=config_dir,
            loader=guarded(loader),
        )
    except HoldoutWindowError as exc:
        raise Stop(
            "3", f"{source}: {exc}. Nothing from it is used; report the incident to the owner"
        ) from exc
    except ValueError as exc:
        raise Stop("2", f"load_panel refused the {source} bars: {exc}") from exc
    return panel


def panel_record(panel: pd.DataFrame) -> dict:
    return {
        "rows": len(panel),
        "hash": panel_hash(panel),
        "first": panel.index[0],
        "last": panel.index[-1],
        "snapshot_id": panel.attrs["snapshot_id"],
        "missing": panel.attrs["alignment"]["missing"]["closes"],
        "dropped": {a: panel.attrs["alignment"]["dropped"][a]["closes"] for a in pf.ASSETS},
    }


def check_panel(source: str, panel: pd.DataFrame, synthetic: bool) -> None:
    """Section 3's checks (stop rule 2): the row count, on real data the panel hash; no close after the last train
    close; every 24-month window holds exactly its closes."""
    if len(panel) != ROWS[source]:
        raise Stop("2", f"{source}: {len(panel)} rows, expected {ROWS[source]} (section 3)")
    if panel.index.max() > LAST_CLOSE:
        raise Stop("3", f"{source}: a close {panel.index.max().isoformat()} after {LAST_CLOSE.isoformat()}")
    if not synthetic:
        got = panel_hash(panel)
        if got != PANEL_HASHES[source]:
            raise Stop("2", f"{source}: panel hash {got} is not {PANEL_HASHES[source]} (other bars)")
    for k, first, last in P.rolling_windows(source):
        try:
            H.window_slice(panel, first, last, missing=H.MISSING_CLOSES[source])
        except H.WindowSliceError as exc:
            raise Stop("2", f"{source} window {k}: {exc}") from exc


def rowset_masks(panel: pd.DataFrame, returns: Mapping[int, float] | None) -> dict[str, np.ndarray]:
    """The kept return rows (rows 1 .. n-1) of each rowset (INTERPRETATIONS["rowsets"]): ``all``; with Kraken's
    yearly returns, also without each bar-year and without the best one and two."""
    years = T.bar_years(panel.index[1:])
    out = {ALL: np.ones(len(panel) - 1, dtype=bool)}
    if returns is None:
        return out
    for y, name in zip(H.TRAIN_YEARS, LOYO, strict=True):
        out[name] = years != y
    for removal, name in zip(P.boom_removals(returns), BOOM, strict=True):
        out[name] = ~np.isin(years, removal["years"])
    return out


def sigma_recheck(panel: pd.DataFrame, sigma: np.ndarray, f: float, lookback: int, starts, settings) -> dict:
    """Section 11's recompute (INTERPRETATIONS["sigma_check"]); a disagreement is stop rule 5."""
    x = K.basket_returns(panel, f)
    rows = sorted(
        set(T.check_closes(panel.index, K.WEEKDAY, lookback).tolist()) | {r for r in starts if r >= lookback}
    )
    listed = []
    for c in rows:
        mine = float(np.std(x[c - lookback + 1 : c + 1], ddof=1) * math.sqrt(365.0))
        theirs = float(sigma[c])
        if abs(mine - theirs) > SIGMA_RTOL * abs(theirs):
            raise Stop("5", f"sigma at row {c} (f {f}, L {lookback}): numpy {mine!r}, engine {theirs!r}")
        for w in settings:
            tau = K.level(w)
            near = mine > 0.0 and abs(4.0 * tau / mine - round(4.0 * tau / mine)) <= 1e-9
            q_mine = 1.0 if mine == 0.0 else math.floor(min(1.0, tau / mine) * 4.0 + 1e-9) / 4.0
            q_theirs = K._q(theirs, tau)
            if near:
                listed.append({"row": c, "w": w, "f": f, "lookback": lookback})
            elif q_mine != q_theirs:
                raise Stop(
                    "5", f"q at row {c} (w {w}, f {f}, L {lookback}): recomputed {q_mine}, engine {q_theirs}"
                )
    return {"rows": len(rows), "near_integer": listed}


# ------------------------------------------------------------------------------------- the runs of a block

KEY_COLUMNS = (
    "run_id",
    "family",
    "source",
    "cost",
    "lookback",
    "wallet",
    "scope",
    "window",
    "w",
    "s",
    "f",
    "kind",
    "u",
    "first_close",
    "last_close",
    "rows",
    "year",
)
MEASURES = (
    "DD",
    "F",
    "worst_week",
    "worst_day",
    "over_cap",
    "cagr",
    "fees_pct_per_year",
    "gas_pct_per_year",
    "first_cost_pct",
    "realised",
    "orders",
    "orders_first",
    "orders_step",
    "orders_drift",
    "orders_limit",
    "orders_per_year",
    "busiest_30d",
)
RULE_COLUMNS = (
    "share",
    "x",
    "x_eq",
    "x_eq_clipped",
    "q_lt1",
    "q_le_half",
    "longest_back_days",
    "step_downs",
    "step_ups",
    "steps_back",
    "rebound_gap",
    "V_X",
    "V_N",
    "c_N",
    "c_X",
    "c_eq",
    "realised_gap",
)
ROWSET_NAMES = (ALL, *LOYO, *BOOM)
V_COLUMNS = tuple(f"V[{name}]" for name in ROWSET_NAMES)
RUN_COLUMNS = (
    *KEY_COLUMNS,
    "status",
    "error",
    *MEASURES,
    *RULE_COLUMNS,
    *V_COLUMNS,
    "q_hash",
    "step_hash",
    "order_hash",
    "snapshot_id",
    "commit",
)
TIME_COLUMNS = ("first_close", "last_close")
INT_COLUMNS = (
    "lookback",
    "window",
    "u",
    "rows",
    "year",
    "orders",
    "orders_first",
    "orders_step",
    "orders_drift",
    "orders_limit",
    "busiest_30d",
    "step_downs",
    "step_ups",
)
BOOL_COLUMNS = ("steps_back", "x_eq_clipped")
TEXT_COLUMNS = (
    "run_id",
    "family",
    "source",
    "cost",
    "scope",
    "kind",
    "status",
    "error",
    "q_hash",
    "step_hash",
    "order_hash",
    "snapshot_id",
    "commit",
)
SERIES_COLUMNS = ("family", "w", "s", "f", "kind", "ret")
FAILURE_COLUMNS = ("run_id", "family", "scope", "window", "error", "traceback")
CSV_COLUMNS = (
    "family",
    "w",
    "s",
    "f",
    "window",
    "kind",
    "status",
    "DD",
    "V_X",
    "V_N",
    "x",
    "x_eq",
    "F",
    "worst_week",
    "cagr",
    "c_N",
    "c_X",
    "fees_pct_per_year",
    "orders",
    "q_lt1",
)
FORBIDDEN_CSV = ("sharpe",)
NOT_RUN = "not run"

_CTX: dict = {}


def run_id(family: str, scope: str, window: int, w, s, f, kind: str, u: int = -1) -> str:
    return f"{family}:{scope}:{window}:{w:g}:{s:g}:{f:g}:{kind}:{u}"


def _frame(rows: list[dict], columns: Sequence[str]) -> pd.DataFrame:
    """Rows to a frame with stable dtypes: timestamps as UTC microseconds, counts as int64 (a failed run's -1),
    booleans as object (None when not set), text as object, every other column float64."""
    frame = pd.DataFrame(rows, columns=list(columns))
    for col in frame.columns:
        if col in TIME_COLUMNS:
            frame[col] = pd.to_datetime(frame[col], utc=True).astype("datetime64[us, UTC]")
        elif col in INT_COLUMNS:
            frame[col] = frame[col].fillna(-1).astype("int64")
        elif col in TEXT_COLUMNS or col in BOOL_COLUMNS:
            frame[col] = frame[col].astype(object)
        elif col != "ret":
            frame[col] = frame[col].astype("float64")
    return frame


def _num(x):
    return math.nan if x is None else x


class _Block:
    """One block's bookkeeping: its rows, failures, the every-9th book check and the failure logging."""

    def __init__(self, ctx: dict, fam: Family, scope: str, window: int, first, last, rows: int):
        self.ctx = ctx
        self.fam = fam
        self.common = {
            "family": fam.name,
            "source": fam.source,
            "cost": fam.cost,
            "lookback": fam.lookback,
            "wallet": fam.wallet,
            "scope": scope,
            "window": window,
            "first_close": first,
            "last_close": last,
            "rows": rows,
            "year": first.year,
            "snapshot_id": ctx["snapshot_id"],
            "commit": ctx["commit"],
        }
        self.costs = ctx["costs"][(fam.cost, fam.wallet)]
        self.limits = ctx["limits"]
        self.runs: list[dict] = []
        self.failures: list[dict] = []
        self.series: list[dict] = []
        self.i = 0

    def base(self, w, s, f, kind: str, u: int = -1) -> dict:
        rid = run_id(self.fam.name, self.common["scope"], self.common["window"], w, s, f, kind, u)
        return {
            **self.common,
            "run_id": rid,
            "w": float(w),
            "s": float(s),
            "f": float(f),
            "kind": kind,
            "u": u,
        }

    def row(self, base: dict, status: str, error: str = "", **values) -> dict:
        row = {**base, "status": status, "error": error, **values}
        self.runs.append(row)
        return row

    def run(self, base: dict, bars: pd.DataFrame, make: Callable[[], pd.DataFrame], *, s, w):
        """One run with its checks and measures, or a logged failure (None)."""
        due = self.i % BOOK_CHECK_EVERY == 0
        self.i += 1
        try:
            result = make()
            K.check_order_targets(result, self.limits)
            if due:
                P.check_book(result, bars, self.costs)
            measures = K.run_measures(result, self.costs, s=s, w=w)
        except K.ConsistencyError as exc:
            raise Stop("5", f"{base['run_id']}: {exc}") from exc
        except Stop:
            raise
        except Exception as exc:  # a failed run is logged and the grid goes on (stop rule 4)
            error = f"{type(exc).__name__}: {exc}"
            self.row(base, "failed", error)
            self.failures.append(
                {
                    "run_id": base["run_id"],
                    "family": self.fam.name,
                    "scope": self.common["scope"],
                    "window": self.common["window"],
                    "error": error,
                    "traceback": traceback.format_exc(),
                }
            )
            return None
        return result, measures

    def frames(self) -> dict:
        return {
            "runs": _frame(self.runs, RUN_COLUMNS),
            "series": pd.DataFrame(self.series, columns=list(SERIES_COLUMNS)),
            "failures": pd.DataFrame(self.failures, columns=list(FAILURE_COLUMNS)),
        }


def independent_x(share) -> float:
    """x recomputed here (section 11): the exact sum of rows 0 .. n-2 as one fraction, rounded once."""
    from fractions import Fraction

    a = np.asarray(share, dtype=float)[:-1]
    return float(sum(Fraction(v) for v in a.tolist()) / len(a))


def _yardstick(blk: _Block, bars, share, f, kind_base: dict, *, s, w):
    def make():
        res = K.run_yardstick(bars, share, f, limits=blk.limits, costs=blk.costs)
        K.check_yardstick(res, share, f)
        return res

    return blk.run(kind_base, bars, make, s=s, w=w)


def _cell(blk: _Block, bars: pd.DataFrame, qp: K.QPath, w, s, f, i_close) -> dict:
    """The rule, N, X and X_eq on one run's bars, logged; returns the runs that succeeded."""
    limits, costs = blk.limits, blk.costs
    share = s * np.asarray(qp.q, dtype=float)
    x = K.matched_share(share)
    if x != independent_x(share):
        raise Stop("5", f"x {x!r} is not the recomputed mean {independent_x(share)!r} (section 11)")
    rule = blk.run(
        blk.base(w, s, f, "rule"),
        bars,
        lambda: K.run_rule(bars, qp, s, f, limits=limits, costs=costs),
        s=s,
        w=w,
    )
    n_run = _yardstick(blk, bars, s, f, blk.base(w, s, f, "N"), s=s, w=w)
    x_run = _yardstick(blk, bars, x, f, blk.base(w, s, f, "X"), s=s, w=w)
    v = None if rule is None or x_run is None else K.ride_v(rule[1]["DD"], x_run[1]["DD"])
    xeq_base = blk.base(w, s, f, "X_eq")
    eq, eq_run = None, None
    if v is None:
        blk.row(xeq_base, NOT_RUN, "V is MISSING (section 6)")
    else:
        eq = K.equal_calm_share(x, v, f, limits)
        eq_run = _yardstick(blk, bars, eq["share"], f, xeq_base, s=s, w=w)
        if eq_run is not None:
            blk.row(xeq_base, K.OK, share=eq["share"], order_hash=eq_run[0].attrs["order_hash"], **eq_run[1])
    for kind, run, target in (("N", n_run, s), ("X", x_run, x)):
        if run is not None:
            blk.row(
                blk.base(w, s, f, kind), K.OK, share=target, order_hash=run[0].attrs["order_hash"], **run[1]
            )
    if rule is not None:
        extra = {
            "x": x,
            "x_eq": None if eq is None else eq["x_eq"],
            "x_eq_clipped": None if eq is None else eq["clipped"],
        }
        if n_run is not None:
            extra.update(K.rule_measures(qp, rule[0], n_run[0], i_close))
        if n_run is not None and x_run is not None:
            extra.update(K.compare(rule[1], n_run[1], x_run[1], None if eq_run is None else eq_run[1]))
        blk.row(
            blk.base(w, s, f, "rule"),
            K.OK,
            share=s,
            q_hash=K.q_hash(qp),
            step_hash=K.step_hash(rule[0]),
            order_hash=rule[0].attrs["order_hash"],
            **{k: _num(v_) for k, v_ in extra.items()},
            **rule[1],
        )
    return {"rule": rule, "N": n_run, "X": x_run, "x": x}


def _window_block(name: str, k: int) -> dict:
    ctx = _CTX
    fam = FAMILY[name]
    grid: Grid = ctx["grid"]
    panel = ctx["panels"][fam.source]
    first, last = {j: (a, z) for j, a, z in P.rolling_windows(fam.source)}[k]
    try:
        piece = H.window_slice(panel, first, last, missing=H.MISSING_CLOSES[fam.source])
    except H.WindowSliceError as exc:
        raise Stop("2", f"{fam.source} window {k}: {exc}") from exc
    r0 = int(panel.index.get_loc(first))
    stop = r0 + len(piece)
    blk = _Block(ctx, fam, "window", k, first, last, len(piece))
    for w in grid.settings:
        for s, f in grid.mixes:
            sig = ctx["sigma"][(fam.source, f, fam.lookback)]
            full = ctx["full_q"][(fam.source, f, fam.lookback, w)]
            qp = K.q_path(panel, w, f, start=r0, stop=stop, lookback=fam.lookback, sigma=sig)
            if len(qp.checks):
                c0 = int(qp.checks[0])
                if not np.array_equal(qp.q[c0:], full.q[r0 + c0 : stop]):
                    raise Stop(
                        "5", f"{name} window {k} w {w}: its q differs from the full panel's (section 11)"
                    )
            i_close = ctx["index"][(fam.source, f)][r0:stop]
            _cell(blk, piece, qp, w, s, f, i_close)
    return blk.frames()


def _span_block(name: str, w: float, s: float, f: float) -> dict:
    ctx = _CTX
    fam = FAMILY[name]
    grid: Grid = ctx["grid"]
    panel = ctx["panels"][fam.source]
    n = len(panel)
    blk = _Block(ctx, fam, "span", -1, panel.index[0], panel.index[-1], n)
    qp = ctx["full_q"][(fam.source, f, fam.lookback, w)]
    cell = _cell(blk, panel, qp, w, s, f, ctx["index"][(fam.source, f)])
    masks = ctx["rowsets"][fam.name]
    rule, x_run = cell["rule"], cell["X"]

    def v_of(a: pd.DataFrame, b: pd.DataFrame) -> dict:
        ra, rb = a["ret"].to_numpy()[1:], b["ret"].to_numpy()[1:]
        return {
            f"V[{m}]": _num(K.ride_v(K.down_day(ra, keep), K.down_day(rb, keep))) for m, keep in masks.items()
        }

    if rule is not None and x_run is not None:
        blk.runs[-1].update(v_of(rule[0], x_run[0]))  # the rule's row is the cell's last
        for kind, run in (("rule", rule), ("X", x_run)):
            blk.series.append(
                {"family": name, "w": w, "s": s, "f": f, "kind": kind, "ret": run[0]["ret"].to_numpy()}
            )
    if not fam.copies:
        return blk.frames()
    schedule = K.copy_schedule(qp, s)
    t0, sh0 = K.shifted_copy(schedule, 0, n, f)
    if rule is not None:
        zero = K.ride_run(panel, t0, limits=blk.limits, costs=blk.costs)
        same = (
            np.array_equal(t0, rule[0].attrs["targets"])
            and np.array_equal(sh0, s * qp.q)
            and zero.equals(rule[0])
            and zero.attrs["order_hash"] == rule[0].attrs["order_hash"]
        )
        if not same:
            raise Stop("5", f"{name} {w} {s} {f}: copy 0 is not the rule bit for bit (section 11)")
    want = sorted(schedule.share.tolist())
    for u in grid.offsets(fam.source, fam.lookback).tolist():
        targets, share = K.shifted_copy(schedule, u, n, f)
        if sorted(T.shifted(schedule, u).share.tolist()) != want:
            raise Stop("5", f"{name} copy {u}: its multiset of check q's is not the rule's (section 11)")
        x_u = K.matched_share(share)
        copy = blk.run(
            blk.base(w, s, f, "copy", u),
            panel,
            lambda t=targets: K.ride_run(panel, t, limits=blk.limits, costs=blk.costs),
            s=s,
            w=w,
        )
        mix = _yardstick(blk, panel, x_u, f, blk.base(w, s, f, "copy_X", u), s=s, w=w)
        if mix is not None:
            blk.row(blk.base(w, s, f, "copy_X", u), K.OK, share=x_u, **mix[1])
        if copy is not None:
            vs = (
                v_of(copy[0], mix[0]) if mix is not None else dict.fromkeys(V_COLUMNS[: len(masks)], math.nan)
            )
            blk.row(
                blk.base(w, s, f, "copy", u),
                K.OK,
                share=x_u,
                order_hash=copy[0].attrs["order_hash"],
                **copy[1],
                **vs,
            )
    return blk.frames()


def run_block(task: tuple) -> dict:
    """One block in a worker; a stop comes back as ``{"stop": (rule, message)}``."""
    try:
        fn = _window_block if task[0] == "window" else _span_block
        return {**fn(*task[1:]), "task": task}
    except Stop as exc:
        return {"stop": (exc.rule, str(exc).split(": ", 1)[1]), "task": task}


def _init_worker(ctx: dict) -> None:
    _CTX.clear()
    _CTX.update(ctx)


def run_blocks(ctx: dict, workers: int, on_result: Callable[[dict], None] | None = None) -> list[dict]:
    """Every block, in task order, on ``workers`` processes (forked; 1 = this process). After a stop no new block
    starts; with workers, the blocks already running finish and are returned after the stopping one."""
    todo = tasks(ctx["grid"])
    _init_worker(ctx)
    results: list[dict] = []

    def keep(result: dict) -> None:
        results.append(result)
        if on_result is not None:
            on_result(result)

    if workers == 1:
        for task in todo:
            keep(run_block(task))
            if "stop" in results[-1]:
                break
        return results
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("fork"),
        initializer=_init_worker,
        initargs=(ctx,),
    ) as pool_:
        futures = [pool_.submit(run_block, task) for task in todo]
        try:
            for i, future in enumerate(futures):
                keep(future.result())
                if "stop" in results[-1]:
                    later = futures[i + 1 :]
                    for other in later:
                        other.cancel()
                    for other in later:
                        if not other.cancelled():
                            keep(other.result())
                    break
        except BaseException:
            for future in futures:
                future.cancel()
            raise
        return results


def block_name(task: tuple) -> str:
    if task[0] == "window":
        return f"window-{task[1]}-{task[2]:02d}".replace(" ", "_")
    _, name, w, s, f = task
    return f"span-{name}-{w:g}-{s:g}-{f:g}".replace(" ", "_")


BLOCK_TABLES = ("runs", "series", "failures")


def write_block(folder: Path, block: dict) -> None:
    for table in BLOCK_TABLES:
        write_parquet(block[table], Path(folder) / f"{block_name(block['task'])}.{table}.parquet")


# ------------------------------------------------------------------------------------- the tables

KIND_ORDER = {k: i for i, k in enumerate((*K.KINDS, *K.COPY_KINDS))}
FAMILY_ORDER = {fam.name: i for i, fam in enumerate(FAMILIES)}
RUN_SORT = ("family", "scope", "window", "w", "s", "f", "u", "kind")


def sort_rows(frame: pd.DataFrame, keys: Sequence[str] = RUN_SORT) -> pd.DataFrame:
    helper = {}
    for key in keys:
        col = frame[key]
        if key == "family":
            helper[f"_k_{key}"] = col.map(FAMILY_ORDER).to_numpy()
        elif key == "kind":
            helper[f"_k_{key}"] = col.map(KIND_ORDER).to_numpy()
        else:
            helper[f"_k_{key}"] = col.to_numpy()
    tmp = frame.assign(**helper).sort_values(list(helper), kind="stable")
    return tmp.drop(columns=list(helper)).reset_index(drop=True)


def concat(blocks: Sequence[dict], name: str) -> pd.DataFrame:
    frames = [b[name] for b in blocks if len(b[name])]
    if not frames:
        return blocks[0][name].iloc[:0].copy() if blocks else pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def check_counts(runs: pd.DataFrame, grid: Grid) -> dict:
    """Every run logged (hard rule 8): section 7's count per family and scope, failures included; no run id twice."""
    want = expected_counts(grid)
    for name, c in want["families"].items():
        for scope in ("window", "span"):
            got = int(((runs["family"] == name) & (runs["scope"] == scope)).sum())
            if got != c[f"{scope}s"]:
                raise Stop("5", f"{name} logged {got} {scope} runs, expected {c[f'{scope}s']} (section 7)")
    if runs["run_id"].duplicated().any():
        raise Stop("5", "two runs share a run id")
    if len(runs) != want["total"]:
        raise Stop("5", f"{len(runs)} runs logged, expected {want['total']} (section 7)")
    return {"got": len(runs), "expected": want["total"]}


def steps_check(runs: pd.DataFrame) -> dict:
    """INTERPRETATIONS["steps_check"]."""
    rules = runs[(runs["kind"] == "rule").to_numpy() & (runs["status"] == K.OK).to_numpy()]
    groups = rules.groupby(["source", "lookback", "f", "w", "scope", "window"], sort=True)
    differ = 0
    for key, part in groups:
        if part["q_hash"].nunique() != 1 or part["step_hash"].nunique() != 1:
            raise Stop("5", f"the steps of {key} depend on s, costs or the wallet (section 11)")
        for _, same_s in part.groupby("s"):
            differ += int(same_s["order_hash"].nunique() > 1)
    return {"groups": groups.ngroups, "pairs_whose_orders_differ": differ}


def runs_csv(runs: pd.DataFrame) -> pd.DataFrame:
    w = runs[runs["scope"].to_numpy() == "window"]
    return w.reindex(columns=list(CSV_COLUMNS))


def csv_text(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, float_format="%.6g", lineterminator="\n")


# ------------------------------------------------------------------------------------------ the statistics


def _cell_rows(runs: pd.DataFrame, family: str, w, s, f) -> pd.DataFrame:
    return runs[
        (runs["family"] == family).to_numpy()
        & (runs["scope"] == "span").to_numpy()
        & (runs["w"] == w).to_numpy()
        & (runs["s"] == s).to_numpy()
        & (runs["f"] == f).to_numpy()
    ]


def span_statistics(runs: pd.DataFrame, series: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    """Section 9 per family, rowset and cell: RISK-X (and the cost flag) on the kept rows, E1 from the copies' V,
    Holm per (family, rowset, mix) and the label. One index set per (source, rowset), generated once."""
    grid: Grid = ctx["grid"]
    rets = {
        (r.family, r.w, r.s, r.f, r.kind): np.asarray(r.ret, dtype=float)[1:] for r in series.itertuples()
    }
    out = []
    needs: dict[tuple[str, str], list[tuple[Family, str]]] = {}
    for name in grid.families:
        fam = FAMILY[name]
        for m in ctx["rowsets"][name]:
            needs.setdefault((fam.source, m), []).append((fam, m))
    for (_source, m), users in needs.items():
        keep = ctx["rowsets"][users[0][0].name][m]
        idx = K.index_set(int(keep.sum()), resamples=grid.resamples)
        for fam, _ in users:
            for w in grid.settings:
                for s, f in grid.mixes:
                    rows = _cell_rows(runs, fam.name, w, s, f)
                    failed = bool(((rows["status"] == "failed") & (rows["kind"] != "X_eq")).any())
                    a, b = rets.get((fam.name, w, s, f, "rule")), rets.get((fam.name, w, s, f, "X"))
                    stats = (
                        K.risk_x(a[keep], b[keep], idx)
                        if a is not None and b is not None
                        else {"missing": "a run failed"}
                    )
                    rule = rows[(rows["kind"] == "rule").to_numpy() & (rows["status"] == K.OK).to_numpy()]
                    steps = bool(rule["steps_back"].iloc[0]) if len(rule) else True
                    cell = {
                        "family": fam.name,
                        "rowset": m,
                        "w": w,
                        "s": s,
                        "f": f,
                        "failed": failed,
                        "steps": steps,
                        "missing": failed or stats.get("missing") is not None,
                        **{
                            k: stats.get(k)
                            for k in ("V", "V_lo", "V_hi", "p_calm", "p_rough", "p_eq", "g", "cost_p")
                        },
                        "cost_flag": stats.get("cost_flag"),
                        "rows": int(keep.sum()),
                    }
                    if fam.copies:
                        copies = rows[rows["kind"].to_numpy() == "copy"]
                        v0 = rule[f"V[{m}]"].iloc[0] if len(rule) else math.nan
                        expected = len(grid.offsets(fam.source, fam.lookback))
                        vs = copies[f"V[{m}]"].tolist() if len(copies) == expected else [math.nan]
                        ev = K.e1(v0, vs)
                        cell.update(e1_rank_p=ev["rank_p"], e1_holds=ev["holds"], copies=ev["copies"])
                    out.append(cell)
        del idx
    table = pd.DataFrame(out)
    labelled = []
    for (name, _m, _s, _f), part in table.groupby(["family", "rowset", "s", "f"], sort=False):
        if FAMILY[name].copies:
            labelled += K.label_family(part.to_dict("records"))
        else:
            labelled += [{**c, "holm": None, "label": None} for c in part.to_dict("records")]
    frame = pd.DataFrame(labelled)
    for col in ("label", "holm"):  # a family without copies has none: None, never NaN
        frame[col] = frame[col].astype(object).where(frame[col].notna(), None)
    frame["_k"] = frame["family"].map(FAMILY_ORDER)
    frame["_r"] = frame["rowset"].map({n: i for i, n in enumerate(ROWSET_NAMES)})
    frame = frame.sort_values(["_k", "_r", "w", "s", "f"], kind="stable").drop(columns=["_k", "_r"])
    return frame.reset_index(drop=True)


# ------------------------------------------------------------------------------------------ the decisions


def window_pool(runs: pd.DataFrame, family: str, windows: Iterable[int] | None = None) -> pd.DataFrame:
    p = runs[(runs["family"] == family).to_numpy() & (runs["scope"] == "window").to_numpy()]
    if windows is not None:
        p = p[p["window"].isin(list(windows)).to_numpy()]
    return p


def labels_of(spans: pd.DataFrame, family: str, rowset: str = ALL) -> pd.DataFrame:
    return spans[(spans["family"] == family).to_numpy() & (spans["rowset"] == rowset).to_numpy()]


def decide(runs: pd.DataFrame, spans: pd.DataFrame, ctx: dict) -> dict:
    """D1 on the three pools, D2 (the boom, Binance and 2x checks), D3 and the flags of section 9.5."""
    grid: Grid = ctx["grid"]

    def d1_on(family: str, rowset: str = ALL, windows=None) -> dict:
        return K.d1(
            window_pool(runs, family, windows),
            labels_of(spans, family, rowset),
            settings=grid.settings,
            mixes=grid.mixes,
        )

    headline = d1_on(HEADLINE)
    checks: dict[str, dict | None] = {}
    boom = {}
    kraken = sorted(set(window_pool(runs, HEADLINE)["window"].tolist()))
    for removal, name in zip(P.boom_removals(ctx["year_returns"]), BOOM, strict=True):
        kept = P.windows_without(kraken, removal["years"])
        boom[name] = {"years": removal["years"], "windows": kept}
        checks[f"boom: {name}"] = d1_on(HEADLINE, name, kept) if len(kept) >= K.BOOM_MIN_WINDOWS else None
    pools = {HEADLINE: headline}
    for check, family in CHECK_FAMILIES.items():
        pools[family] = checks[check] = d1_on(family) if family in grid.families else None
    head_spans = labels_of(spans, HEADLINE)
    flags = []
    for w in grid.settings:
        for s, f in grid.mixes:
            at = (spans["w"] == w).to_numpy() & (spans["s"] == s).to_numpy() & (spans["f"] == f).to_numpy()
            mine = spans[at]
            rule = _cell_rows(runs, HEADLINE, w, s, f)
            by_kind = {r.kind: r for r in rule[rule["status"] == K.OK].itertuples()}
            more = (
                by_kind["X_eq"].cagr - by_kind["rule"].cagr
                if "X_eq" in by_kind and "rule" in by_kind
                else None
            )
            head = mine[(mine["family"] == HEADLINE).to_numpy() & (mine["rowset"] == ALL).to_numpy()]
            flags.append(
                {
                    "w": w,
                    "s": s,
                    "f": f,
                    "cost_flag": None if not len(head) else head["cost_flag"].iloc[0],
                    "same_calm_more_return": more,
                    "labels": {
                        f"{r.family} {r.rowset}": r.label
                        for r in mine.itertuples()
                        if isinstance(r.label, str)
                    },
                }
            )
    return {
        "D1": {name: d for name, d in pools.items()},
        "D2": K.d2(headline, checks),
        "boom": boom,
        "D3": {
            name: K.d3(window_pool(runs, name), labels_of(spans, name), headline["default"], ctx["budget"])
            for name in grid.families
        },
        "flags": flags,
        "headline_labels": head_spans[["w", "s", "f", "label"]].to_dict("records"),
    }


# ------------------------------------------------------------------------------------------- the timing


def timing_panel() -> pd.DataFrame:
    panel = T.garch_panel(TIMING_PANEL)
    panel.attrs["snapshot_id"] = "synthetic"
    return panel


def measure_throughput(limits: Mapping, config_dir: Path | None, reps: int) -> dict:
    """A1 (INTERPRETATIONS["time"]): medians over ``reps`` repetitions and the projections of run 0 and A0."""
    panel = timing_panel()
    w, s, f = TIMING_CELL
    costs = cost_models(config_dir)[("1x", K.DEPOSIT)]
    lim = {"min_cash": limits["min_cash"], "max_coin": limits["max_coin"]}
    _, first, last = P.rolling_windows("KRAKEN")[TIMING_WINDOW]
    piece = H.window_slice(panel, first, last, missing=H.MISSING_CLOSES["KRAKEN"])
    r0 = int(panel.index.get_loc(first))
    seconds: dict[str, list[float]] = {
        k: [] for k in ("span", "copy", "a0_copy", "window", "index_set", "risk_x")
    }
    sig = K.swing(panel, f)
    for _ in range(reps):
        t0 = time.perf_counter()
        qp = K.q_path(panel, w, f, sigma=sig)
        rule = K.run_rule(panel, qp, s, f, limits=lim, costs=costs)
        K.check_order_targets(rule, lim)
        P.check_book(rule, panel, costs)
        K.run_measures(rule, costs, s=s, w=w)
        t1 = time.perf_counter()
        sch = K.copy_schedule(qp, s)
        tg, sh = K.shifted_copy(sch, 53, len(panel), f)
        copy = K.ride_run(panel, tg, limits=lim, costs=costs)
        K.run_measures(copy, costs, s=s, w=w)
        mix = K.run_yardstick(panel, K.matched_share(sh), f, limits=lim, costs=costs)
        K.run_measures(mix, costs, s=s, w=w)
        t2 = time.perf_counter()
        wq = K.q_path(panel, w, f, start=r0, stop=r0 + len(piece), sigma=sig)
        win = K.run_rule(piece, wq, s, f, limits=lim, costs=costs)
        P.check_book(win, piece, costs)
        K.run_measures(win, costs, s=s, w=w)
        t3 = time.perf_counter()
        idx = K.index_set(len(panel) - 1)
        t4 = time.perf_counter()
        K.risk_x(rule["ret"].to_numpy()[1:], mix["ret"].to_numpy()[1:], idx)
        t5 = time.perf_counter()
        light = K.ride_run(panel, tg, limits=lim, costs=costs)
        K.down_day(light["ret"].to_numpy()[1:])
        mix = K.run_yardstick(panel, K.matched_share(sh), f, limits=lim, costs=costs)
        K.down_day(mix["ret"].to_numpy()[1:])
        t6 = time.perf_counter()
        steps = (
            ("span", t0, t1),
            ("copy", t1, t2),
            ("window", t2, t3),
            ("index_set", t3, t4),
            ("risk_x", t4, t5),
        )
        for key, a, b in (*steps, ("a0_copy", t5, t6)):
            seconds[key].append(b - a)
    per = {k: float(np.median(v)) for k, v in seconds.items()}
    return {"reps": reps, "seconds": per, **project(per)}


def project(per: Mapping[str, float]) -> dict:
    """The projections (CPU-minutes) of run 0 (section 7's counts) and of A0 at 100 and 80 panels a set."""
    counts = expected_counts(PLAN_GRID)
    cells = len(PLAN_GRID.settings) * len(PLAN_GRID.mixes)
    span_runs = sum(cells * len(K.KINDS) for _ in counts["families"])
    pairs = sum(cells * c["copies_per_cell"] for c in counts["families"].values())
    window_runs = sum(c["windows"] for c in counts["families"].values())
    resamplings = cells * (len(ROWSET_NAMES) + len(FAMILIES) - 1)
    run0 = (
        span_runs * per["span"]
        + pairs * per["copy"]
        + window_runs * per["window"]
        + 10 * per["index_set"]
        + resamplings * per["risk_x"]
    ) / 60.0
    guarded = len(T.guarded_offsets(CHECKS[("KRAKEN", 14)]))
    per_panel = (
        4 * (3 * per["span"] + guarded * per["a0_copy"]) + 4 * 49 * 3 * per["window"] + 4 * per["risk_x"]
    )
    return {
        "counts": {
            "span_runs": span_runs,
            "copy_pairs": pairs,
            "window_runs": window_runs,
            "index_sets": 10,
            "resamplings": resamplings,
        },
        "cpu_minutes": run0,
        "a0_cpu_minutes": {str(n): (5 * n * per_panel + per["index_set"]) / 60.0 for n in (100, 80)},
        "limit_cpu_minutes": CPU_MINUTES_MAX,
        "a0_limit_cpu_minutes": A0_CPU_MINUTES_MAX,
    }


# ------------------------------------------------------------------------------------------------ the run


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--out-dir", default=str(DEFAULT_OUT), help="results folder (default results/keep-risk-steady)"
    )
    ap.add_argument("--catalog-dir", default=str(DEFAULT_CATALOG))
    ap.add_argument(
        "--config-dir", default=None, help="folder with costs.yaml, splits.yaml, risk_levels.yaml"
    )
    ap.add_argument("--amendment", type=int, default=None, metavar="K", help="amendment run K (1 or 2)")
    ap.add_argument("--workers", type=int, default=2, help="worker processes (default 2)")
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED", help="dry run on synthetic bars")
    ap.add_argument("--fast", action="store_true", help="dry runs only: the small grid")
    ap.add_argument(
        "--time", action="store_true", help="only the A1 timing, into --out-dir (a scratch folder)"
    )
    return ap.parse_args(argv)


def timing_only(args) -> int:
    if args.synthetic is not None or args.amendment is not None or args.fast:
        raise Refusal("--time runs on its own (with --out-dir and optionally --config-dir)")
    out = Path(args.out_dir)
    check_out_dir(out)
    config_dir = Path(args.config_dir) if args.config_dir else None
    limits = steady_limits(config_dir)
    timing = measure_throughput(limits, config_dir, TIMING_REPS)
    write_json(out / "timing.json", {"utc": utc_now(), "label": LABEL, "timing": timing})
    print(
        f"A1 timing: run 0 {timing['cpu_minutes']:.1f} CPU-minutes (limit {CPU_MINUTES_MAX:g}); A0 "
        f"{timing['a0_cpu_minutes']['100']:.1f} at 100 panels a set (limit {A0_CPU_MINUTES_MAX:g}). Written to "
        f"{out / 'timing.json'}",
        flush=True,
    )
    return 0


def start_guards(args) -> dict:
    """Every start guard (module docstring), before anything is written."""
    synthetic = args.synthetic is not None
    if not synthetic and args.fast:
        raise Refusal("--fast is for synthetic dry runs only")
    if args.amendment == 0:
        raise Refusal("--amendment 0: run 0 is run without --amendment")
    if args.workers < 1:
        raise Refusal(f"--workers {args.workers}: at least 1")
    k = 0 if args.amendment is None else args.amendment
    out = Path(args.out_dir)
    config_dir = Path(args.config_dir) if args.config_dir else None
    catalog_dir = Path(args.catalog_dir)
    if synthetic:
        check_out_dir(out)
    else:
        check_real_paths(out, config_dir, catalog_dir)
    data = "synthetic" if synthetic else "real"
    check_layout(out, k, synthetic)
    if k:
        check_earlier_runs(out, k, data, bool(args.fast))
    check_runlog(runlog_path(out, synthetic), k, data)
    plan_text = PLAN.read_text()
    if k and not synthetic and not amendment_row_present(plan_text, k):
        raise Refusal(
            f"--amendment {k}: PLAN.md section 13 lists no '- **Amendment run {k}' row (stop rule 6)"
        )
    git = git_state()
    if git["dirty"] and not synthetic:
        raise Refusal(
            "the git tree is dirty (git status --porcelain --untracked-files=all): commit first (stop rule 1). "
            f"Changes: {git['changes'][:10]}"
        )
    prior = None if synthetic else prior_amendments(plan_text)
    hashes = file_hashes(config_dir)
    snapshot = read_snapshot(catalog_dir, synthetic)
    limits = steady_limits(config_dir)
    grid = FAST if args.fast else PLAN_GRID
    check_grid_targets(grid.mixes, limits)
    costs = cost_models(config_dir)
    try:
        timing = measure_throughput(limits, config_dir, TIMING_REPS_FAST if args.fast else TIMING_REPS)
    except Exception as exc:  # the engine fails on the timing's synthetic panel: nothing can run
        raise Refusal(f"the A1 timing failed: {type(exc).__name__}: {exc}") from exc
    if not synthetic and timing["cpu_minutes"] > CPU_MINUTES_MAX:
        raise Refusal(
            f"stop rule 7: the projection is {timing['cpu_minutes']:.1f} CPU-minutes, above {CPU_MINUTES_MAX:g}: ask "
            "the owner before any run"
        )
    return {
        "k": k,
        "out": out,
        "config_dir": config_dir,
        "catalog_dir": catalog_dir,
        "synthetic": synthetic,
        "data": data,
        "git": git,
        "prior_amendments": prior,
        "hashes": hashes,
        "snapshot": snapshot,
        "limits": limits,
        "grid": grid,
        "costs": costs,
        "timing": timing,
    }


def run(args) -> int:
    g = start_guards(args)
    k, out, synthetic, grid = g["k"], g["out"], g["synthetic"], g["grid"]
    run_dir = out / f"run{k}"
    start = {
        "utc": utc_now(),
        "script": SCRIPT,
        "study": STUDY,
        "run": k,
        "data": g["data"],
        "synthetic_seed": args.synthetic,
        "fast": bool(args.fast),
        "workers": args.workers,
        "platform": {
            "sys_platform": sys.platform,
            "system": platform.system(),
            "python": sys.version.split()[0],
        },
        "git": g["git"],
        "prior_amendments": g["prior_amendments"],
        "config_hash": config_hash(g["hashes"]),
        "file_hashes": g["hashes"],
        "risk_limits": g["limits"],
        "costs": {f"{c} {w:g}": asdict(m) for (c, w), m in g["costs"].items()},
        "grid": grid.record(),
        "thresholds": thresholds(),
        "timing": g["timing"],
        "snapshot": g["snapshot"],
        "out_dir": str(out),
        "config_dir": None if g["config_dir"] is None else str(g["config_dir"]),
        "catalog_dir": str(g["catalog_dir"]),
        "interpretations": INTERPRETATIONS,
        "label": LABEL,
    }
    run_dir.mkdir(parents=True)
    write_json(run_dir / "start.json", start)
    log = runlog_path(out, synthetic)
    append_runlog(
        log,
        {
            "utc": start["utc"],
            "script": SCRIPT,
            "run": k,
            "commit": g["git"]["commit"],
            "dirty": g["git"]["dirty"],
            "config_hash": start["config_hash"],
            "snapshot_id": g["snapshot"]["snapshot_id"],
            "data": g["data"],
            "out_dir": str(out),
        },
    )
    summary = {"study": STUDY, "run": k, "data": g["data"], "status": "started", "label": LABEL}
    write_json(run_dir / "summary.json", summary)
    print(
        f"run {k} ({g['data']}, grid {grid.name}) started; config hash {start['config_hash'][:16]}",
        flush=True,
    )
    t0 = time.time()

    def end(status: str, event: str, **extra) -> None:
        summary.update(status=status, runtime_s=time.time() - t0, **extra)
        write_json(run_dir / "summary.json", summary)
        append_runlog(log, {"utc": utc_now(), "script": SCRIPT, "run": k, "data": g["data"], "event": event})

    try:
        results = study(args, g, start, run_dir, summary)
        if file_hashes(g["config_dir"]) != g["hashes"]:
            raise Stop("5", "a hashed file changed during the run (section 11)")
        write_outputs(results, g, run_dir)
    except Stop as exc:
        end(f"stopped: {exc}", f"stop rule {exc.rule}", stop={"rule": exc.rule, "message": str(exc)})
        print(f"STOP: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        end(f"crashed: {type(exc).__name__}: {exc}", "crashed", traceback=traceback.format_exc())
        raise
    end("complete", "complete", **results["summary"])
    print(
        f"run {k} complete in {time.time() - t0:.1f}s: {results['summary']['counts']['got']} runs, "
        f"{results['summary']['failed_runs']} failed; default {results['summary']['headline']}",
        flush=True,
    )
    return 0


def prepare(panels: Mapping[str, pd.DataFrame], grid: Grid, returns: Mapping[int, float]) -> dict:
    """The point-in-time signal per source, f and look-back (the swing, each w's full q path, the index I) and the
    rowsets, before any backtest; with section 11's sigma recompute."""
    sigma, full_q, index, rechecks = {}, {}, {}, {}
    for name in grid.families:
        fam = FAMILY[name]
        panel = panels[fam.source]
        starts = [
            int(panel.index.get_loc(a))
            for k, a, _ in P.rolling_windows(fam.source)
            if k in grid.windows[fam.source]
        ]
        for _, f in grid.mixes:
            key = (fam.source, f, fam.lookback)
            if key not in sigma:
                sigma[key] = K.swing(panel, f, fam.lookback)
                rechecks[f"{fam.source} f={f:g} L={fam.lookback}"] = sigma_recheck(
                    panel, sigma[key], f, fam.lookback, starts, grid.settings
                )
                for w in grid.settings:
                    full_q[(*key, w)] = K.q_path(panel, w, f, lookback=fam.lookback, sigma=sigma[key])
            if (fam.source, f) not in index:
                index[(fam.source, f)] = P.index_signal(panel, f)["I"].to_numpy()
    rowsets = {
        name: rowset_masks(panels[FAMILY[name].source], returns if name == HEADLINE else None)
        for name in grid.families
    }
    return {"sigma": sigma, "full_q": full_q, "index": index, "rowsets": rowsets, "sigma_check": rechecks}


def study(args, g: dict, start: dict, run_dir: Path, summary: dict) -> dict:
    """From the panels to the tables and decisions."""
    loader = synthetic_bar_loader(args.synthetic) if g["synthetic"] else None
    panels = {}
    for source in H.SOURCES:
        panels[source] = load_study_panel(
            source, catalog_dir=g["catalog_dir"], config_dir=g["config_dir"], loader=loader
        )
    start["panels"] = {source: panel_record(panels[source]) for source in H.SOURCES}
    returns = H.year_returns(panels["KRAKEN"])  # the boom ranking, before any backtest
    start["year_returns"] = returns
    write_json(run_dir / "start.json", start)
    for source in H.SOURCES:
        check_panel(source, panels[source], g["synthetic"])
    grid = g["grid"]
    ctx = {
        "grid": grid,
        "panels": panels,
        **prepare(panels, grid, returns),
        "year_returns": returns,
        "limits": {"min_cash": g["limits"]["min_cash"], "max_coin": g["limits"]["max_coin"]},
        "budget": g["limits"]["max_drawdown_budget"],
        "costs": g["costs"],
        "snapshot_id": g["snapshot"]["snapshot_id"],
        "commit": g["git"]["commit"],
    }
    progress = summary["blocks"] = {"blocks": len(tasks(grid)), "logged": 0, "runs_logged": 0}
    summary.update(status="panels loaded", sigma_check=ctx["sigma_check"])
    write_json(run_dir / "summary.json", summary)

    def logged(block: dict) -> None:
        if "stop" in block:
            return
        write_block(run_dir / "blocks", block)
        progress["logged"] += 1
        progress["runs_logged"] += len(block["runs"])
        write_json(run_dir / "summary.json", summary)

    t = time.time()
    blocks = run_blocks(ctx, args.workers, on_result=logged)
    for block in blocks:
        if "stop" in block:
            rule, message = block["stop"]
            raise Stop(rule, f"{message} (block {block['task']})")
    runs = sort_rows(concat(blocks, "runs"))
    series = concat(blocks, "series")
    failures = concat(blocks, "failures")
    write_parquet(runs, run_dir / "runs.parquet")
    write_parquet(series, run_dir / "series.parquet")
    write_parquet(failures, run_dir / "failures.parquet")
    counts = check_counts(runs, grid)
    steps = steps_check(runs)
    spans = span_statistics(runs, series, ctx)
    write_parquet(spans, run_dir / "spans.parquet")
    decided = decide(runs, spans, ctx)
    failed = int((runs["status"] == "failed").sum())
    headline = {"default": decided["D1"][HEADLINE]["default"], "label": decided["D2"]["label"]}
    decision = {
        "label": LABEL,
        "study": STUDY,
        "run": g["k"],
        "data": g["data"],
        "grid": grid.name,
        "thresholds": thresholds(),
        "counts": counts,
        "failed_runs": failed,
        "steps_check": steps,
        "budget": ctx["budget"],
        "headline": headline,
        **decided,
    }
    return {
        "runs": runs,
        "csv": runs_csv(runs),
        "spans_csv": spans,
        "decision": decision,
        "summary": {
            "counts": counts,
            "failed_runs": failed,
            "steps_check": steps,
            "grid_runtime_s": time.time() - t,
            "headline": jsonable(headline),
            "decision_tables": "decision.json (this folder; byte-identical to the tracked copy)",
        },
    }


def write_outputs(results: dict, g: dict, run_dir: Path) -> None:
    decision = json_text(results["decision"])
    write_text(run_dir / "decision.json", decision)
    tracked = tracked_dir(g["out"], g["synthetic"])
    write_text(tracked / "decision.json", decision)
    write_text(tracked / "runs.csv", csv_text(results["csv"]))
    write_text(tracked / "spans.csv", csv_text(results["spans_csv"]))


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return timing_only(args) if args.time else run(args)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
