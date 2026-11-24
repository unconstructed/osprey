"""buy-the-dip: the study's one script (``research/buy-the-dip/PLAN.md`` sections 3-14; section numbers below are that
file's).

SCOUTING ONLY. Every number comes from the reference portfolio engine (``lab.runner.portfolio``, driven by
``lab.runner.dipbuy`` through ``protect.run_overlay``), not NautilusTrader (AGENTS.md hard rule 3), with the
PLACEHOLDER costs of ``config/costs.yaml`` and exchange candles standing in for Base prices. It claims no edge and
approves nothing. It reads the train years only: every panel comes from ``lab.data.panel.load_panel`` with
``last_close`` = 2023-01-01 00:00 UTC (the last train close); validate and test stay unread.

    uv run python research/buy-the-dip/run.py                                  # run 0 on real data (2 workers)
    uv run python research/buy-the-dip/run.py --amendment 1                    # amendment run 1 (stop rule 6)
    uv run python research/buy-the-dip/run.py --synthetic 7 --fast --out-dir <scratch>   # dry run
    uv run python research/buy-the-dip/run.py --time --out-dir <scratch>       # the A1 timing only

Start guards, all before anything is written (exit 2): a real run uses the pinned folders only (``--out-dir``
results/buy-the-dip, ``--config-dir`` unset or config/, ``--catalog-dir`` data/catalog) and a dry run never writes into
results/buy-the-dip or anywhere in the repo; ``--fast`` is for dry runs only; run 0 refuses an earlier run folder (a
real run 0: any results/buy-the-dip/) and ``--amendment k`` refuses unless 1 <= k <= 2, ``run<k-1>/start.json``
exists, ``run<k>/`` does not, every earlier run is the same kind of run and (real data) PLAN.md section 12's
amendments list holds ``- **Amendment run k``; the RUNLOG must not hold this run number; a real run refuses a dirty git
tree and a catalog whose bars hash is not the pinned one; ``risk_limits("steady")`` must give exactly min_cash 0.20 and
max_coin 0.60 (section 4) and every start's targets must pass ``check_targets`` with them and h = 0.02; a real run
whose projection (the A1 timing, made again at start) is above 240 CPU-minutes does not start (stop rule 7).

Then, before any bar is read: ``run<k>/start.json`` (the start record) and one RUNLOG line. Then the panels (row
counts, panel hashes on real data, every calendar window present: stop rule 2; a close after 2023-01-01: stop rule
3), BTC's calendar-year returns on Kraken (D2's boom ranking, written before any backtest), the index and its 365-day
high for each source and f, stage 1 (Kraken 1x) in worker processes by window blocks, each block's tables written to
``run<k>/blocks/`` as it returns, D1, stage 2 (Binance 1x and Kraken 2x), the 1x/2x check, D2 and D3, the consistency
stops of section 10 (stop rule 5: exit 3, recorded in ``summary.json``), and the outputs: ``runs.parquet``,
``ladders.parquet`` and ``failures.parquet`` (written before any count or decision), ``summary.json`` and
``decision.json`` in ``run<k>/``; the tracked ``RUNLOG.jsonl``, ``runs.csv`` and ``decision.json`` in this folder
(dry runs: ``<out>/tracked/``). Exit codes: 0 done, 2 refused at start, 3 stopped.

The computations (the ladder, the twins, the measures, the rules D1-D3) live in tested code, ``lab/runner/dipbuy.py``.
This file holds the pinned values, the guards, the grid's bookkeeping and the outputs. ``research/`` is never imported
by ``lab/``.
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
from lab.runner import dipbuy as DB
from lab.runner import holdmix as H
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner.reference import Costs
from lab.runner.steady import panel_hash

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
SCRIPT = "run.py"
STUDY = "buy-the-dip"
DEFAULT_OUT = REPO / "results" / STUDY
DEFAULT_CATALOG = REPO / "data" / "catalog"

INTERVAL = "1d"
LAST_CLOSE = H.LAST_CLOSE  # 2023-01-01 00:00 UTC, the last train close (section 3)
SNAPSHOT_ID = "1746a21b75683e76"  # section 3 (recorded; the hashes decide)
BARS_SHA256 = "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"  # section 3
PANEL_HASHES = {
    "KRAKEN": "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
    "BINANCE": "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
}
ROWS = {"KRAKEN": 2190, "BINANCE": 1963}  # section 3
MAX_AMENDMENTS = 2  # stop rule 6
CPU_MINUTES_MAX = 240.0  # stop rule 7
TIMING_REPS = 20
TIMING_REPS_FAST = 3
TIMING_START = (0.0, 0.50)  # A1: the all-USDC start, the even split
TIMING_BUSY = DB.Setting(0.10, 0.05, 0.10, 1.00)  # A1: the most lines and the shallowest trigger (section 7)
TIMING_ROWS = 731  # a 24-month window
COST_LEVELS = ("1x", "2x")
STRESS = 2.0  # section 3: Costs.from_yaml(capital_usd=5000).stressed(2.0)
STAGE1_POOL = ("KRAKEN", "1x")
STAGE2_POOLS = (("BINANCE", "1x"), ("KRAKEN", "2x"))
CONFIG_FILES = ("config/costs.yaml", "config/splits.yaml", "config/risk_levels.yaml")
BOOK_CHECK_EVERY = 9  # section 10: the accounting on every 9th run of a block
LABEL = DB.LABEL

INTERPRETATIONS = {
    **{f"dipbuy.{k}": v for k, v in DB.READINGS_PINNED.items()},
    "fast": "--fast is a small dry-run grid (4 settings spanning Y, Z, X and M, 2 starts, Kraken windows 0, 24, 48 "
    "and Binance 8, 48). The rules run on it mechanically; a boom removal leaves fewer than 12 windows, so those "
    "checks are MISSING. The grid in use is in start.json",
    "time": "A real run repeats the A1 timing at start (synthetic data only, no market bar: on a 731-row window of "
    "make_panel(synthetic_market(2190, seed=21)), the busiest dip setting (Y 0.10, Z 0.05, X 0.10, M 1.00) from the "
    "all-USDC start with f 0.50, its dca and lump twins and the hold run, each with every check and measure of a "
    "real run, the accounting included) and refuses to start when every run of the plan's grid charged at its "
    "kind's median projects above 240 CPU-minutes (stop rule 7). Dry runs record it and never refuse on it",
    "dirty": "A dirty git tree (git status --porcelain --untracked-files=all prints anything) refuses real runs only",
    "run0": "A real run 0 refuses when results/buy-the-dip/ exists; a dry run 0 refuses when <out>/run<j>/ exists",
    "same_kind_of_run": "--amendment k refuses unless every earlier run has the same data (real or synthetic) and "
    "--fast setting",
    "runlog": "A run number the RUNLOG already holds for the same data (any line) is refused. Besides the start line, "
    "an event line is appended when a run completes, stops or crashes",
    "snapshot": "Section 3's snapshot id is recorded with the catalog's; the bars hash and the panel hashes decide "
    "(stop rule 2 names them, not the id), as in protect-gains",
    "limits": "risk_limits('steady') must give min_cash exactly 0.20 and max_coin exactly 0.60 (section 4: 'the run "
    "refuses to start if the file's values differ from these'), and each start's targets must pass check_targets "
    "with them and h = 0.02; the budget as read is recorded and shown in D3 (not enforced)",
    "config_hash": "The config hash covers the plan's list (dipbuy.py, protect.py, portfolio.py, holdmix.py, "
    "reference.py, trend.py, lab/validation/*.py, the data loaders, config/*.yaml, pyproject.toml, uv.lock, this "
    "script and PLAN.md) and the files those import for the numbers (interface.py, steady.py for the panel hash, "
    "lab/data/panel.py, catalog.py, external.py, loaders.py and lab/config.py)",
    "stop_rule_3": "The loader is wrapped: a close after 2023-01-01 00:00 UTC stops the run before load_panel sees it "
    "(load_panel refuses it too); a tz-naive index is read as UTC. Recorded in summary.json and the RUNLOG",
    "data_stops": "load_panel refusing the bars, a row count other than 2190 / 1963, another panel hash (real data), "
    "or a 24-month window whose closes are not all present (2018-01-13 is Kraken's one pinned missing close): stop "
    "rule 2, before any backtest",
    "failures": "A run that raises (other than a consistency stop) is logged as failed with its error text and "
    "traceback, and the grid goes on; a failed dip run's twins are logged as failed too (their total is the dip "
    "run's); every decision that needs its pool is MISSING (stop rule 4)",
    "consistency": "Stop rule 5 in each run: the step's book against the engine's weights at every close (bit for "
    "bit) and its values against the run's own returns (1e-12); every order's targets through check_targets (R1); "
    "each dip run's triggers, crossings and re-arms against the one-pass recompute from I and H; each twin's total "
    "against its dip run's, and the twins of a dip run whose ordered total is 0 against hold bit for bit; the book "
    "of coin units and cash (protect.check_book) on every 9th run of a block; every run's fee check "
    "(holdmix.money_metrics); after each stage the counts; after stage 2 the Kraken 1x and 2x dip runs' triggers, "
    "crossings and re-arms (dipbuy.events_hash); at the end every hashed file hashed again",
    "cost_check": "Section 10's 'order closes equal at 1x and 2x' is read as the ladder's own decisions, the "
    "triggers, the crossings and the re-arms, which come from I alone and must be equal (else stop rule 5). The "
    "orders actually sent can differ where a cap leaves nothing or a limit fix falls on another close (the weights "
    "move by a hair with the costs); summary.json counts those runs (orders_differ_1x_2x), as a description",
    "runs_csv": "One row per run (section 14): its keys, status, F, delta, G, T_dca, T_lump, T_hold and the buying "
    "measures, the USDC left, the worst knife and the fees; no Sharpe, end value or total return column",
    "parallel": "Workers are forked processes (multiprocessing 'fork'; start.json records the platform: fork is safe "
    "on Linux, where the real run is made); rows are sorted by a pinned key, so the outputs do not depend on the "
    "number of workers",
    "logging": "Each block's tables (runs, ladders, failures) are written to run<k>/blocks/ as soon as the block "
    "returns, so a stop, a crash or a killed process keeps every block computed so far. A block that stops is not "
    "written (its stop names the run); with 2 workers, blocks already running when another block stops finish and "
    "are written too. After each stage the three tables are written to run<k>/ before any count or decision",
    "boom": "D2's boom checks drop from the Kraken 1x pool every 24-month window overlapping BTC's best calendar year "
    "(then its two best), by protect.boom_removals and protect.windows_without, years by bar day and ranked on "
    "Kraken's closes (start.json year_returns, written before any backtest); fewer than 12 windows left gives "
    "MISSING",
    "year": "D3's 'year of each window's first close' is the calendar year of the window's first close (Kraken "
    "windows 0-11: 2017, ..., 48: 2021)",
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
    """What a run covers: the settings (Y, Z, X, M), the start wallets (s0, f) and the windows per source (Kraken's
    serve stage 1 and the Kraken 2x pool, Binance's the Binance 1x pool)."""

    settings: tuple[tuple[float, float, float, float], ...]
    starts: tuple[tuple[float, float], ...]
    windows: Mapping[str, tuple[int, ...]]
    name: str = "plan"

    @property
    def decidable(self) -> bool:
        return bool(self.settings) and bool(self.starts) and all(self.windows.get(s) for s in H.SOURCES)

    def record(self) -> dict:
        return jsonable({**asdict(self), "decidable": self.decidable, "counts": expected_counts(self)})


PLAN_GRID = Grid(
    settings=tuple(tuple(s) for s in DB.SETTINGS),
    starts=DB.STARTS,
    windows={s: _all_windows(s) for s in H.SOURCES},
)
FAST = Grid(
    settings=(
        (0.10, 0.05, 0.10, 1.00),
        (0.10, 0.10, 0.25, 0.50),
        (0.20, 0.20, 0.10, 0.25),
        (0.30, 0.05, 0.25, 1.00),
    ),
    starts=((0.0, 0.50), (0.30, 0.75)),
    windows={"KRAKEN": (0, 24, 48), "BINANCE": (8, 48)},
    name="fast",
)


def expected_counts(grid: Grid) -> dict:
    """Section 7's counts for ``grid``: each (start, window) has 3 runs per setting (dip, dca, lump) and one hold run.
    Stage 1: Kraken 1x; stage 2: Binance 1x and Kraken 2x. For the plan's grid: 31,948 + 58,680 = 90,628."""
    per = 3 * len(grid.settings) + 1
    nk, nb = len(grid.windows.get("KRAKEN", ())), len(grid.windows.get("BINANCE", ()))
    ns = len(grid.starts)
    stage1 = per * ns * nk
    stage2 = per * ns * (nb + nk)
    units = ns * (nk + nb + nk)
    return {
        "stage1": stage1,
        "stage2": stage2,
        "total": stage1 + stage2,
        "per_start_window": per,
        "dip": len(grid.settings) * units,
        "dca": len(grid.settings) * units,
        "lump": len(grid.settings) * units,
        "hold": units,
    }


def pinned_values() -> dict:
    """The pinned values of the config hash."""
    return jsonable(
        {
            "grid": asdict(PLAN_GRID),
            "windows": {s: P.rolling_windows(s) for s in H.SOURCES},
            "missing_closes": H.MISSING_CLOSES,
            "deposit": DB.DEPOSIT,
            "headroom": DB.HEADROOM,
            "limits": {"min_cash": DB.STEADY_MIN_CASH, "max_coin": DB.STEADY_MAX_COIN},
            "high_days": DB.HIGH_DAYS,
            "dca": {"pieces": DB.DCA_PIECES, "days": DB.DCA_DAYS},
            "thresholds": thresholds(),
            "stress": STRESS,
            "snapshot_id": SNAPSHOT_ID,
            "bars_sha256": BARS_SHA256,
            "panel_hashes": PANEL_HASHES,
            "rows": ROWS,
            "last_close": LAST_CLOSE,
            "book_check_every": BOOK_CHECK_EVERY,
            "readings": DB.READINGS_PINNED,
        }
    )


def thresholds() -> dict:
    return {
        "PERCENTILE": DB.PERCENTILE,
        "DESCRIBE_PERCENTILES": DB.DESCRIBE_PERCENTILES,
        "ACTIVE": "2 * windows with a ladder order >= windows",
        "USABLE": "Q <= Q_dca and max(F) <= max(F_dca), and Active, at every start",
        "TIE_TOL": DB.TIE_TOL,
        "K_TOL": DB.K_TOL,
        "BOOM_MIN_WINDOWS": DB.BOOM_MIN_WINDOWS,
    }


# ------------------------------------------------------------------------------------- hashing, git, json


def frozen_paths() -> list[str]:
    """The repo-relative files of the config hash (section 10; INTERPRETATIONS["config_hash"]), sorted."""
    validation = {p.relative_to(REPO).as_posix() for p in (REPO / "lab" / "validation").glob("*.py")}
    return sorted(
        validation
        | {
            "research/buy-the-dip/PLAN.md",
            "research/buy-the-dip/run.py",
            "lab/runner/dipbuy.py",
            "lab/runner/protect.py",
            "lab/runner/holdmix.py",
            "lab/runner/portfolio.py",
            "lab/runner/reference.py",
            "lab/runner/trend.py",
            "lab/runner/interface.py",
            "lab/runner/steady.py",
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
    """SHA-256 of every hashed file; the three ``config/*.yaml`` files are read from ``config_dir`` (the files the
    run uses; default ``config/``) under their ``config/`` names."""
    cfg = Path(config_dir) if config_dir is not None else CONFIG_DIR
    return {
        rel: sha256_file(cfg / Path(rel).name if rel in CONFIG_FILES else REPO / rel)
        for rel in frozen_paths()
    }


def config_hash(hashes: Mapping[str, str]) -> str:
    """SHA-256 over a JSON blob of the per-file hashes (sorted by path) and the pinned values."""
    blob = json.dumps({"files": dict(sorted(hashes.items())), "pinned": pinned_values()}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def git_state(repo: Path = REPO) -> dict:
    """``commit`` (HEAD), ``dirty`` (``git status --porcelain --untracked-files=all`` prints anything; git-ignored
    files do not count) and the first porcelain lines."""

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
    """Write through a temporary file, so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_json(path: Path, obj) -> None:
    write_text(path, json_text(obj))


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write through a temporary file, so a crash never leaves half a table."""
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
    """Where the tracked files go: this folder for real runs, ``<out>/tracked`` for dry runs."""
    return Path(out) / "tracked" if synthetic else HERE


def runlog_path(out: Path, synthetic: bool) -> Path:
    return tracked_dir(out, synthetic) / "RUNLOG.jsonl"


def amendment_row_present(plan_text: str, k: int) -> bool:
    """PLAN.md section 12's list of amendments (from the line starting ``**Amendments:**`` to the heading ``## 13.``)
    holds a line starting with ``- **Amendment run k``."""
    start = re.search(r"^\*\*Amendments:?\*\*", plan_text, re.MULTILINE)
    end = re.search(r"^## 13\.", plan_text, re.MULTILINE)
    if start is None or end is None or end.start() < start.start():
        return False
    pattern = re.compile(rf"^- \*\*Amendment run {k}\b", re.MULTILINE)
    return bool(pattern.search(plan_text[start.start() : end.start()]))


# ------------------------------------------------------------------------------------------- start guards


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path) -> None:
    """A dry run (or the timing) never writes into results/buy-the-dip or anywhere in the repo."""
    where = Path(out).resolve()
    if _inside(where, DEFAULT_OUT.resolve()) or _inside(where, REPO.resolve()):
        raise Refusal(
            f"--out-dir {out}: a synthetic dry run never writes into {DEFAULT_OUT} or inside the repo; use a "
            "scratch folder"
        )


def check_real_paths(out: Path, config_dir: Path | None, catalog_dir: Path) -> None:
    """A real run writes only to results/buy-the-dip and reads only config/ and data/catalog/."""
    if Path(out).resolve() != DEFAULT_OUT.resolve():
        raise Refusal(f"--out-dir {out}: a real run writes only to {DEFAULT_OUT}")
    if config_dir is not None and Path(config_dir).resolve() != (REPO / "config").resolve():
        raise Refusal(f"--config-dir {config_dir}: a real run reads config/ only")
    if Path(catalog_dir).resolve() != DEFAULT_CATALOG.resolve():
        raise Refusal(
            f"--catalog-dir {catalog_dir}: a real run reads only {DEFAULT_CATALOG} (PLAN.md section 3)"
        )


def check_layout(out: Path, k: int, synthetic: bool) -> None:
    """Stop rule 6's start refusals for run ``k`` (0 = run 0)."""
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
    """An amendment run continues the same kind of run (INTERPRETATIONS["same_kind_of_run"])."""
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
    """``snapshot_id`` and ``bars_content_sha256`` from ``SNAPSHOT.json`` (metadata only, no bar). A real run refuses
    another bars hash (section 3, stop rule 2). Dry runs read nothing."""
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
            f"the catalog's bars hash {snap['bars_content_sha256']!r} is not {BARS_SHA256} (PLAN.md section 3, stop "
            "rule 2)"
        )
    if not isinstance(snap["snapshot_id"], str) or not snap["snapshot_id"]:
        raise Refusal(f"{path} names no snapshot_id")
    snap["plan_snapshot_id"] = SNAPSHOT_ID
    return snap


def steady_limits(config_dir: Path | None) -> dict:
    """``portfolio.risk_limits("steady")``, refused unless min_cash is 0.20 and max_coin 0.60 as read (section 4;
    INTERPRETATIONS["limits"])."""
    try:
        limits = pf.risk_limits("steady", config_dir)
    except (ValueError, OSError) as exc:
        raise Refusal(f"risk_limits('steady') does not read: {exc}") from exc
    got = (limits["min_cash"], limits["max_coin"])
    if got != (DB.STEADY_MIN_CASH, DB.STEADY_MAX_COIN):
        raise Refusal(
            f"the steady level's limits as read are min_cash {got[0]!r} and max_coin {got[1]!r}, not the plan's "
            f"{DB.STEADY_MIN_CASH} and {DB.STEADY_MAX_COIN} (section 4): amend the plan before any run"
        )
    return limits


def check_starts(starts: Iterable, limits: Mapping) -> None:
    """Every start wallet of the plan and of the grid in use must pass ``check_targets`` with the limits as read and
    h = 0.02 (section 4)."""
    try:
        for s0, f in (*DB.STARTS, *starts):
            pf.check_targets(
                *DB.start_targets(s0, f),
                min_cash=limits["min_cash"],
                max_coin=limits["max_coin"],
                headroom=DB.HEADROOM,
            )
    except ValueError as exc:
        raise Refusal(f"the Steady limits as read refuse a start wallet (PLAN.md section 4): {exc}") from exc


def cost_models(config_dir: Path | None) -> dict[str, Costs]:
    """``Costs.from_yaml(capital_usd=5000)`` (1x) and its ``stressed(2.0)`` (2x), as read (section 3)."""
    path = None if config_dir is None else Path(config_dir) / "costs.yaml"
    base = Costs.from_yaml(path, capital_usd=DB.DEPOSIT)
    return {"1x": base, "2x": base.stressed(STRESS)}


# --------------------------------------------------------------------------------------------- the timing


def timing_panel() -> pd.DataFrame:
    return pf.make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")


def measure_throughput(limits: Mapping, config_dir: Path | None, reps: int) -> dict:
    """A1 (INTERPRETATIONS["time"]): medians over ``reps`` repetitions of each kind of run with every check and
    measure of a real run, and the projection over the plan's grid."""
    panel = timing_panel()
    piece = panel.iloc[:TIMING_ROWS]
    costs = cost_models(config_dir)["1x"]
    lim = {"min_cash": limits["min_cash"], "max_coin": limits["max_coin"]}
    s0, f = TIMING_START
    sig = DB.window_signal(DB.dip_signal(panel, f), piece.index)
    seconds: dict[str, list[float]] = {k: [] for k in DB.KINDS}
    shape = {}
    for _ in range(reps):
        t0 = time.perf_counter()
        hold = _hold_run(piece, costs, lim, s0, f, book=True)
        t1 = time.perf_counter()
        dip = _dip_run(piece, costs, lim, s0, f, TIMING_BUSY, sig, book=True)
        t2 = time.perf_counter()
        seconds["hold"].append(t1 - t0)
        seconds["dip"].append(t2 - t1)
        for kind in ("dca", "lump"):
            t3 = time.perf_counter()
            _twin_run(kind, piece, costs, lim, s0, f, dip[1]["ordered_usd"], hold[0], book=True)
            seconds[kind].append(time.perf_counter() - t3)
        shape = {k: dip[1][k] for k in ("ladders", "orders", "pieces", "limit_fixes")}
    counts = expected_counts(PLAN_GRID)
    per = {k: float(np.median(v)) for k, v in seconds.items()}
    cpu_s = sum(counts[k] * per[k] for k in DB.KINDS)
    return {
        "reps": reps,
        "rows": TIMING_ROWS,
        "start": TIMING_START,
        "busy": tuple(TIMING_BUSY),
        "busy_shape": shape,
        "seconds_per_run": per,
        "runs": {k: counts[k] for k in DB.KINDS},
        "cpu_minutes": cpu_s / 60.0,
        "wall_minutes_on_2_workers": cpu_s / 120.0,
        "limit_cpu_minutes": CPU_MINUTES_MAX,
        "python": sys.version.split()[0],
    }


# ------------------------------------------------------------------------------------------------ the data

SYNTHETIC_DAYS = 2191  # closes 2017-01-02 .. 2023-01-01, the Kraken grid
SYNTHETIC_FIRST = "2017-01-02"


def synthetic_bar_loader(seed: int) -> Callable:
    """A stand-in for ``lab.data.catalog.load_bars`` that serves SYNTHETIC daily bars on the plan's date grid, for dry
    runs and tests only: Kraken from close 2017-01-02 with ETH's 2018-01-13 bar missing; Binance from close 2017-08-18
    (the same bars times a small per-bar factor). Snapshot id ``"synthetic"``."""
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
    (stop rule 3) before ``load_panel`` sees the bars. ``None`` means ``lab.data.catalog.load_bars``, looked up at
    call time."""

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
    """``load_panel(source, "1d", last_close=2023-01-01 00:00 UTC)`` through :func:`guarded`; a close after
    ``LAST_CLOSE`` is stop rule 3, any other refusal of the bars stop rule 2."""
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
    close; then every 24-month window must hold exactly its closes (section 7)."""
    if len(panel) != ROWS[source]:
        raise Stop("2", f"{source}: {len(panel)} rows, expected {ROWS[source]} (PLAN.md section 3)")
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


# ------------------------------------------------------------------------------------- the runs of a block

KEY_COLUMNS = ("run_id", "stage", *DB.RUN_KEYS, "first_close", "last_close", "rows", "year")
COMPARE_COLUMNS = ("T_dca", "T_lump", "T_hold", "G")
RUN_COLUMNS = (
    *KEY_COLUMNS,
    "status",
    "error",
    *DB.RUN_MEASURES,
    *COMPARE_COLUMNS,
    "events_hash",
    "orders_hash",
    "snapshot_id",
    "commit",
)
LADDER_TABLE_COLUMNS = ("run_id", "stage", *DB.RUN_KEYS, *DB.LADDER_COLUMNS)
FAILURE_COLUMNS = ("run_id", "stage", "source", "cost", "window", "error", "traceback")
TIME_COLUMNS = ("first_close", "last_close", "start_ts", "rearm_ts")
INT_COLUMNS = (
    "stage",
    "window",
    "rows",
    "year",
    "ladders",
    "ladders_filled",
    "orders",
    "pieces",
    "unfilled_lines",
    "limit_fixes",
    "ladder",
    "start",
    "lines",
    "crossed",
    "first_order",
    "last_order",
    "rearm",
)
TEXT_COLUMNS = (
    "run_id",
    "source",
    "cost",
    "kind",
    "status",
    "error",
    "events_hash",
    "orders_hash",
    "snapshot_id",
    "commit",
)
CSV_COLUMNS = (
    "run_id",
    "stage",
    *DB.RUN_KEYS,
    "status",
    "F",
    "delta",
    "G",
    "T_dca",
    "T_lump",
    "T_hold",
    "ladders",
    "ladders_filled",
    "orders",
    "pieces",
    "first_order_days",
    "ordered_usd",
    "sent_usd",
    "capped_usd",
    "blocked_usd",
    "unfilled_usd",
    "unfilled_lines",
    "limit_fixes",
    "usdc_left",
    "knife_worst",
    "fees_pct_per_year",
    "gas_pct_per_year",
)
FORBIDDEN_CSV = ("sharpe", "v_end", "total_return")

_CTX: dict = {}


def _g(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else format(float(x), "g")


def run_id(stage, source, cost, window, s0, f, kind, setting=None) -> str:
    y, z, x, m = setting if setting is not None else (None,) * 4
    return f"{stage}:{source}:{cost}:{window}:{s0:g}:{f:g}:{kind}:{_g(y)}:{_g(z)}:{_g(x)}:{_g(m)}"


def _params(kind: str, s0: float, f: float, limits: Mapping, setting=None, total=None) -> dict:
    p = {"kind": kind, "s0": s0, "f": f, "min_cash": limits["min_cash"], "max_coin": limits["max_coin"]}
    if setting is not None:
        p.update(zip(DB.SETTING_KEYS, setting, strict=True))
    if total is not None:
        p["total"] = total
    return p


def _common_checks(res: pd.DataFrame, piece: pd.DataFrame, costs: Costs, limits: Mapping, book: bool) -> None:
    DB.check_order_targets(res, limits)
    DB.check_values(res)
    if book:
        P.check_book(res, piece, costs)


def _hold_run(piece, costs, limits, s0, f, *, book: bool) -> tuple[pd.DataFrame, dict]:
    res = DB.dip_buy(_params("hold", s0, f, limits), piece, costs)
    _common_checks(res, piece, costs, limits, book)
    return res, DB.run_measures(res, costs)


def _dip_run(piece, costs, limits, s0, f, setting, sig, *, book: bool) -> tuple[pd.DataFrame, dict]:
    res = DB.dip_buy(_params("dip", s0, f, limits, setting=setting), piece, costs, sig)
    _common_checks(res, piece, costs, limits, book)
    DB.check_events(res, sig)
    return res, DB.run_measures(res, costs, sig)


def _twin_run(kind, piece, costs, limits, s0, f, total, hold, *, book: bool) -> tuple[pd.DataFrame, dict]:
    res = DB.dip_buy(_params(kind, s0, f, limits, total=total), piece, costs)
    _common_checks(res, piece, costs, limits, book)
    DB.check_twin(res, total, hold)
    return res, DB.run_measures(res, costs)


def _row(base: dict, status: str, error: str = "", measures: Mapping | None = None) -> dict:
    row = {
        **base,
        "status": status,
        "error": error,
        **dict.fromkeys(DB.RUN_MEASURES, math.nan),
        **dict.fromkeys(COMPARE_COLUMNS, math.nan),
        "events_hash": "",
        "orders_hash": "",
    }
    if measures is not None:
        row.update(measures)
    return row


def _block(stage: int, source: str, cost: str, k: int) -> dict:
    ctx = _CTX
    grid: Grid = ctx["grid"]
    first, last = {w: (a, z) for w, a, z in P.rolling_windows(source)}[k]
    try:
        piece = H.window_slice(ctx["panels"][source], first, last, missing=H.MISSING_CLOSES[source])
    except H.WindowSliceError as exc:
        raise Stop("2", f"{source} window {k}: {exc}") from exc
    costs = ctx["costs"][cost]
    limits = ctx["limits"]
    common = {
        "stage": stage,
        "source": source,
        "cost": cost,
        "window": k,
        "first_close": first,
        "last_close": last,
        "rows": len(piece),
        "year": first.year,
        "snapshot_id": ctx["snapshot_id"],
        "commit": ctx["commit"],
    }
    runs, ladders, failures = [], [], []
    counter = {"i": 0}

    def book() -> bool:
        due = counter["i"] % BOOK_CHECK_EVERY == 0
        counter["i"] += 1
        return due

    def fail(base: dict, exc: Exception | str) -> None:
        error = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
        runs.append(_row(base, "failed", error))
        failures.append(
            {
                "run_id": base["run_id"],
                "stage": stage,
                "source": source,
                "cost": cost,
                "window": k,
                "error": error,
                "traceback": traceback.format_exc() if not isinstance(exc, str) else error,
            }
        )

    def attempt(base: dict, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DB.ConsistencyError as exc:
            raise Stop("5", f"{base['run_id']}: {exc}") from exc
        except Exception as exc:  # a failed run is logged and the grid goes on (stop rule 4)
            fail(base, exc)
            return None

    for s0, f in grid.starts:
        sig = DB.window_signal(ctx["signals"][(source, f)], piece.index)
        start = {**common, "s0": float(s0), "f": float(f)}
        nan_setting = dict.fromkeys(DB.SETTING_KEYS, math.nan)
        hbase = {**start, **nan_setting, "kind": "hold"}
        hbase["run_id"] = run_id(stage, source, cost, k, s0, f, "hold")
        hold = attempt(hbase, _hold_run, piece, costs, limits, s0, f, book=book())
        if hold is not None:
            runs.append(_row(hbase, DB.OK, measures={**hold[1], "orders_hash": DB.orders_hash(hold[0])}))
        for setting in grid.settings:
            keyed = {**start, **dict(zip(DB.SETTING_KEYS, map(float, setting), strict=True))}
            bases = {}
            for kind in ("dip", *DB.TWINS[:2]):
                bases[kind] = {
                    **keyed,
                    "kind": kind,
                    "run_id": run_id(stage, source, cost, k, s0, f, kind, setting),
                }
            dip = attempt(bases["dip"], _dip_run, piece, costs, limits, s0, f, setting, sig, book=book())
            if dip is None:
                for kind in DB.TWINS[:2]:
                    counter["i"] += 1
                    fail(bases[kind], "the dip run failed: its twins have no total (stop rule 4)")
                continue
            res, measures = dip
            total = measures["ordered_usd"]
            twins = {}
            for kind in DB.TWINS[:2]:
                held = None if hold is None else hold[0]
                twins[kind] = attempt(
                    bases[kind], _twin_run, kind, piece, costs, limits, s0, f, total, held, book=book()
                )
                if twins[kind] is not None:
                    runs.append(
                        _row(
                            bases[kind],
                            DB.OK,
                            measures={**twins[kind][1], "orders_hash": DB.orders_hash(twins[kind][0])},
                        )
                    )
            compare = {}
            if hold is not None and all(t is not None for t in twins.values()):
                compare = DB.compare_twins(measures, twins["dca"][1], twins["lump"][1], hold[1])
            runs.append(
                _row(
                    bases["dip"],
                    DB.OK,
                    measures={
                        **measures,
                        **compare,
                        "events_hash": DB.events_hash(res),
                        "orders_hash": DB.orders_hash(res),
                    },
                )
            )
            keys = {key: bases["dip"][key] for key in ("run_id", "stage", *DB.RUN_KEYS)}
            ladders += [{**keys, **row} for row in DB.ladder_rows(res, sig)]
    return {
        "runs": _frame(runs, RUN_COLUMNS),
        "ladders": _frame(ladders, LADDER_TABLE_COLUMNS),
        "failures": pd.DataFrame(failures, columns=list(FAILURE_COLUMNS)),
    }


def _frame(rows: list[dict], columns: Sequence[str]) -> pd.DataFrame:
    """Rows to a frame with stable dtypes, whatever failed: timestamps as UTC microseconds, counts as int64 (a
    failed run's as -1), text as object, every other column float64."""
    frame = pd.DataFrame(rows, columns=list(columns))
    for col in frame.columns:
        if col in TIME_COLUMNS:
            frame[col] = pd.to_datetime(frame[col], utc=True).astype("datetime64[us, UTC]")
        elif col in INT_COLUMNS:
            frame[col] = frame[col].fillna(-1).astype("int64")
        elif col in TEXT_COLUMNS:
            frame[col] = frame[col].astype(object)
        else:
            frame[col] = frame[col].astype("float64")
    return frame


def run_block(task: tuple) -> dict:
    """One (stage, source, cost, window) block in a worker; a stop comes back as ``{"stop": (rule, message)}``."""
    try:
        return {**_block(*task), "task": task}
    except Stop as exc:
        return {"stop": (exc.rule, str(exc).split(": ", 1)[1]), "task": task}


def _init_worker(ctx: dict) -> None:
    _CTX.clear()
    _CTX.update(ctx)


def tasks(grid: Grid, stage: int) -> list[tuple]:
    if stage == 1:
        source, cost = STAGE1_POOL
        return [(1, source, cost, k) for k in grid.windows[source]]
    return [(2, source, cost, k) for source, cost in STAGE2_POOLS for k in grid.windows[source]]


def run_blocks(
    ctx: dict, stage: int, workers: int, on_result: Callable[[dict], None] | None = None
) -> list[dict]:
    """Every block of ``stage``, in task order, on ``workers`` processes (forked; 1 = this process). ``on_result``
    sees each block as it returns. After a stop no new block starts; with workers, the blocks already running finish
    and are returned (and seen) after the stopping one."""
    todo = tasks(ctx["grid"], stage)
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
                    for other in later:  # already running: they finish, and their rows are logged too
                        if not other.cancelled():
                            keep(other.result())
                    break
        except BaseException:
            for future in futures:
                future.cancel()
            raise
        return results


# ------------------------------------------------------------------------------------- the tables

SORT_ORDER = {
    "source": {s: i for i, s in enumerate(H.SOURCES)},
    "cost": {c: i for i, c in enumerate(COST_LEVELS)},
    "kind": {k: i for i, k in enumerate(DB.KINDS)},
}
RUN_SORT = ("stage", "source", "cost", "window", "s0", "f", "Y", "Z", "X", "M", "kind")


def sort_rows(frame: pd.DataFrame, keys: Sequence[str] = RUN_SORT, extra: Sequence[str] = ()) -> pd.DataFrame:
    """Rows in the pinned order: stage, source, cost, window, s0, f, Y, Z, X, M (hold's NaN first), kind (hold, dip,
    dca, lump), then ``extra``."""
    helper = {}
    for key in (*keys, *extra):
        if key in SORT_ORDER:
            helper[f"_k_{key}"] = frame[key].map(SORT_ORDER[key]).to_numpy()
        elif key in DB.SETTING_KEYS:
            col = frame[key].to_numpy(dtype=float)
            helper[f"_k_{key}"] = np.where(np.isnan(col), -np.inf, col)
        else:
            helper[f"_k_{key}"] = frame[key].to_numpy()
    tmp = frame.assign(**helper).sort_values(list(helper), kind="stable")
    return tmp.drop(columns=list(helper)).reset_index(drop=True)


def concat(blocks: Sequence[dict], name: str) -> pd.DataFrame:
    frames = [b[name] for b in blocks if len(b[name])]
    if not frames:
        return blocks[0][name].iloc[:0].copy() if blocks else pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def check_counts(runs: pd.DataFrame, grid: Grid, stage: int) -> dict:
    """Every run logged (hard rule 8): stage ``stage``'s count of section 7 for the grid in use, failures included,
    and no run id twice; else stop."""
    want = expected_counts(grid)[f"stage{stage}"]
    got = int((runs["stage"].to_numpy() == stage).sum())
    if got != want:
        raise Stop("5", f"stage {stage} logged {got} runs, expected {want} (section 7; hard rule 8)")
    if runs["run_id"].duplicated().any():
        raise Stop("5", "two runs share a run id")
    return {"got": got, "expected": want}


def cost_check(runs: pd.DataFrame) -> dict:
    """Section 10 (INTERPRETATIONS["cost_check"]): each Kraken dip run's triggers, crossings and re-arms equal at 1x
    and 2x (else stop rule 5); and how many pairs' sent orders differ (a description)."""
    dips = runs[(runs["kind"].to_numpy() == "dip") & (runs["source"].to_numpy() == "KRAKEN")]
    dips = dips[dips["status"].to_numpy() == DB.OK]
    keys = ["window", "s0", "f", *DB.SETTING_KEYS]
    one = dips[dips["cost"].to_numpy() == "1x"].set_index(keys)
    two = dips[dips["cost"].to_numpy() == "2x"].set_index(keys)
    common = one.index.intersection(two.index)
    if len(common):
        a = one.loc[common, "events_hash"].to_numpy()
        b = two.loc[common, "events_hash"].to_numpy()
        differ = np.flatnonzero(a != b)
        if len(differ):
            raise Stop(
                "5",
                f"{len(differ)} Kraken dip runs' triggers, crossings or re-arms differ between 1x and 2x, e.g. "
                f"{one.loc[common].iloc[int(differ[0])]['run_id']} (section 10)",
            )
        orders = int(
            (one.loc[common, "orders_hash"].to_numpy() != two.loc[common, "orders_hash"].to_numpy()).sum()
        )
    else:
        orders = 0
    return {"pairs": len(common), "events_equal": len(common), "orders_differ_1x_2x": orders}


def runs_csv(runs: pd.DataFrame) -> pd.DataFrame:
    """The tracked ``runs.csv``: one row per run, :data:`CSV_COLUMNS` (no Sharpe, end value or total return)."""
    return runs.reindex(columns=list(CSV_COLUMNS))


def csv_text(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, float_format="%.6g", lineterminator="\n")


# ------------------------------------------------------------------------------------------ the decisions


def pool(runs: pd.DataFrame, source: str, cost: str, windows: Iterable[int] | None = None) -> pd.DataFrame:
    """One pool's runs (all stages), optionally on some windows only."""
    p = runs[(runs["source"].to_numpy() == source) & (runs["cost"].to_numpy() == cost)]
    if windows is not None:
        p = p[p["window"].isin(list(windows)).to_numpy()]
    return p


def boom_checks(runs: pd.DataFrame, returns: Mapping[int, float]) -> dict:
    """D2's boom checks on the Kraken 1x pool: each removal's kept windows and its :func:`dipbuy.d1`, or None
    (MISSING) when fewer than BOOM_MIN_WINDOWS windows are left."""
    k1 = pool(runs, *STAGE1_POOL)
    windows = sorted(set(k1["window"].tolist()))
    out = {}
    for removal in P.boom_removals(returns):
        kept = P.windows_without(windows, removal["years"])
        entry = {"years": removal["years"], "windows": kept, "d1": None}
        if len(kept) >= DB.BOOM_MIN_WINDOWS:
            entry["d1"] = DB.d1(pool(runs, *STAGE1_POOL, windows=kept))
        out[removal["name"]] = entry
    return out


def decide_stage1(runs: pd.DataFrame) -> dict:
    """D1 on the Kraken 1x pool."""
    return {"D1": DB.d1(pool(runs, *STAGE1_POOL))}


def decide_stage2(
    runs: pd.DataFrame, ladders: pd.DataFrame, stage1: Mapping, returns: Mapping, budget: float | None
) -> dict:
    """D2 (the boom, Binance and 2x checks), D3 at the default and the per-setting tables."""
    headline = stage1["D1"]
    boom = boom_checks(runs, returns)
    checks = {name: entry["d1"] for name, entry in boom.items()}
    checks["Binance"] = DB.d1(pool(runs, "BINANCE", "1x"))
    checks["2x costs"] = DB.d1(pool(runs, "KRAKEN", "2x"))
    k1 = pool(runs, *STAGE1_POOL)
    tables = {
        f"{source} {cost}": DB.setting_table(pool(runs, source, cost))
        for source, cost in (STAGE1_POOL, *STAGE2_POOLS)
    }
    return {
        "D2": DB.d2(headline, checks),
        "D3": DB.d3(
            k1, ladders[ladders["run_id"].isin(k1["run_id"]).to_numpy()], headline["default"], budget
        ),
        "checks": {
            "boom": {name: {k: v for k, v in entry.items() if k != "d1"} for name, entry in boom.items()},
            "D1": checks,
        },
        "tables": tables,
    }


# ------------------------------------------------------------------------------------------------ the run


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--out-dir", default=str(DEFAULT_OUT), help="results folder (default results/buy-the-dip)"
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
        f"A1 timing: {timing['cpu_minutes']:.1f} CPU-minutes for the plan's grid (limit {CPU_MINUTES_MAX:g}); about "
        f"{timing['wall_minutes_on_2_workers']:.1f} minutes on 2 workers. Written to {out / 'timing.json'}",
        flush=True,
    )
    return 0


def start_guards(args) -> dict:
    """Every start guard (module docstring), before anything is written; returns what the start record needs."""
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
    if k and not synthetic and not amendment_row_present(PLAN.read_text(), k):
        raise Refusal(
            f"--amendment {k}: PLAN.md section 12 lists no '- **Amendment run {k}' row (stop rule 6)"
        )
    git = git_state()
    if git["dirty"] and not synthetic:
        raise Refusal(
            "the git tree is dirty (git status --porcelain --untracked-files=all): commit first (stop rule 1). "
            f"Changes: {git['changes'][:10]}"
        )
    hashes = file_hashes(config_dir)
    snapshot = read_snapshot(catalog_dir, synthetic)
    limits = steady_limits(config_dir)
    grid = FAST if args.fast else PLAN_GRID
    check_starts(grid.starts, limits)
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
            "start_method": "fork",
        },
        "git": g["git"],
        "config_hash": config_hash(g["hashes"]),
        "file_hashes": g["hashes"],
        "risk_limits": g["limits"],
        "costs": {name: asdict(c) for name, c in g["costs"].items()},
        "grid": grid.record(),
        "windows": {s: P.rolling_windows(s) for s in H.SOURCES},
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
            raise Stop("5", "a hashed file changed during the run (section 10)")
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
        f"run {k} complete in {time.time() - t0:.1f}s: {results['summary']['counts']['total']} runs, "
        f"{results['summary']['failed_runs']} failed; default {results['summary']['headline']}",
        flush=True,
    )
    return 0


def _stage(ctx: dict, stage: int, workers: int, run_dir: Path, summary: dict) -> tuple[pd.DataFrame, ...]:
    progress = summary["grid"][f"stage{stage}"] = {
        "blocks": len(tasks(ctx["grid"], stage)),
        "blocks_logged": 0,
        "runs_logged": 0,
    }

    def logged(block: dict) -> None:  # every run logged: what a block computed stays in the run folder
        if "stop" in block:
            return
        write_block(run_dir / "blocks", block)
        progress["blocks_logged"] += 1
        progress["runs_logged"] += len(block["runs"])
        write_json(run_dir / "summary.json", summary)

    blocks = run_blocks(ctx, stage, workers, on_result=logged)
    for block in blocks:
        if "stop" in block:
            rule, message = block["stop"]
            raise Stop(rule, f"{message} (block {block['task']})")
    runs = sort_rows(concat(blocks, "runs"))
    ladders = sort_rows(concat(blocks, "ladders"), extra=("ladder",))
    failures = concat(blocks, "failures")
    return runs, ladders, failures


def study(args, g: dict, start: dict, run_dir: Path, summary: dict) -> dict:
    """From the panels to the tables and decisions (written here: start.json's panels and yearly returns, each
    block's tables, each stage's tables before its count or decision)."""
    loader = synthetic_bar_loader(args.synthetic) if g["synthetic"] else None
    panels = {}
    for source in H.SOURCES:
        panels[source] = load_study_panel(
            source, catalog_dir=g["catalog_dir"], config_dir=g["config_dir"], loader=loader
        )
    start["panels"] = {source: panel_record(panels[source]) for source in H.SOURCES}  # before any check
    returns = H.year_returns(panels[DB.BOOM_RANK_SOURCE])  # D2's ranking, before any backtest
    start["year_returns"] = returns
    write_json(run_dir / "start.json", start)
    for source in H.SOURCES:
        check_panel(source, panels[source], g["synthetic"])
    grid = g["grid"]
    signals = {
        (source, f): DB.dip_signal(panels[source], f)
        for source in H.SOURCES
        for f in sorted({f for _, f in grid.starts})
    }
    summary.update(status="panels loaded", grid={})
    write_json(run_dir / "summary.json", summary)
    ctx = {
        "grid": grid,
        "panels": panels,
        "signals": signals,
        "limits": {"min_cash": g["limits"]["min_cash"], "max_coin": g["limits"]["max_coin"]},
        "costs": g["costs"],
        "snapshot_id": g["snapshot"]["snapshot_id"],
        "commit": g["git"]["commit"],
    }
    t = time.time()
    runs1, lad1, fails1 = _stage(ctx, 1, args.workers, run_dir, summary)
    write_tables(run_dir, runs1, lad1, fails1)  # before any count or decision
    counts1 = check_counts(runs1, grid, 1)
    stage1 = decide_stage1(runs1) if grid.decidable else None
    summary.update(status="stage 1 complete")
    write_json(run_dir / "summary.json", summary)
    runs2, lad2, fails2 = _stage(ctx, 2, args.workers, run_dir, summary)
    runs = sort_rows(pd.concat([runs1, runs2], ignore_index=True))
    ladders = sort_rows(pd.concat([lad1, lad2], ignore_index=True), extra=("ladder",))
    failures = pd.concat([fails1, fails2], ignore_index=True)
    write_tables(run_dir, runs, ladders, failures)
    counts2 = check_counts(runs, grid, 2)
    costs_checked = cost_check(runs)
    runtime = time.time() - t
    failed = int((runs["status"].to_numpy() != DB.OK).sum())
    budget = g["limits"]["max_drawdown_budget"]
    decided = decide_stage2(runs, ladders, stage1, returns, budget) if stage1 is not None else None
    headline = None
    if stage1 is not None:
        headline = {"default": stage1["D1"]["default"], "label": decided["D2"]["label"]}
    decision = {
        "label": LABEL,
        "study": STUDY,
        "run": g["k"],
        "data": g["data"],
        "grid": grid.name,
        "decidable": grid.decidable,
        "thresholds": thresholds(),
        "counts": {"stage1": counts1, "stage2": counts2, "expected": expected_counts(grid)},
        "failed_runs": failed,
        "cost_check": costs_checked,
        "budget": budget,
        "headline": headline,
        "stage1": stage1,
        "stage2": decided,
    }
    return {
        "runs": runs,
        "csv": runs_csv(runs),
        "decision": decision,
        "summary": {
            "counts": {"stage1": counts1["got"], "stage2": counts2["got"], "total": len(runs)},
            "expected": expected_counts(grid),
            "failed_runs": failed,
            "ladders_logged": len(ladders),
            "cost_check": costs_checked,
            "grid_runtime_s": runtime,
            "headline": jsonable(headline),
            "decision_tables": "decision.json (this folder; byte-identical to the tracked copy)",
        },
    }


def write_tables(run_dir: Path, runs: pd.DataFrame, ladders: pd.DataFrame, failures: pd.DataFrame) -> None:
    for name, table in (("runs", runs), ("ladders", ladders), ("failures", failures)):
        write_parquet(table, run_dir / f"{name}.parquet")


BLOCK_TABLES = ("runs", "ladders", "failures")


def block_name(task: tuple) -> str:
    """``s1-KRAKEN-1x-07``: a block's file prefix in ``run<k>/blocks/``."""
    stage, source, cost, k = task
    return f"s{stage}-{source}-{cost}-{k:02d}"


def write_block(folder: Path, block: dict) -> None:
    for table in BLOCK_TABLES:
        write_parquet(block[table], Path(folder) / f"{block_name(block['task'])}.{table}.parquet")


def write_outputs(results: dict, g: dict, run_dir: Path) -> None:
    """decision.json and the tracked files (the tables are already in ``run_dir``)."""
    decision = json_text(results["decision"])
    write_text(run_dir / "decision.json", decision)
    tracked = tracked_dir(g["out"], g["synthetic"])
    write_text(tracked / "decision.json", decision)
    write_text(tracked / "runs.csv", csv_text(results["csv"]))


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return timing_only(args) if args.time else run(args)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
