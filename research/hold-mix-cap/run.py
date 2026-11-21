"""hold-mix-cap: the study's one script (``research/hold-mix-cap/PLAN.md`` sections 3-13; section numbers below are
that file's).

SCOUTING ONLY. Every number comes from the reference portfolio engine (``lab.runner.portfolio``, driven by
``lab.runner.holdmix``), not NautilusTrader (AGENTS.md hard rule 3), with the PLACEHOLDER costs of
``config/costs.yaml`` and exchange candles standing in for Base prices. It claims no edge, approves nothing and sets
no limit. It reads the train years only: every panel comes from ``lab.data.panel.load_panel`` with ``last_close`` =
2023-01-01 00:00 UTC (the last train close); validate and test stay unread.

    uv run python research/hold-mix-cap/run.py                                  # run 0 on real data (2 workers)
    uv run python research/hold-mix-cap/run.py --amendment 1                    # amendment run 1 (stop rule 7)
    uv run python research/hold-mix-cap/run.py --synthetic 7 --fast --out-dir <scratch>   # dry run
    uv run python research/hold-mix-cap/run.py --time --out-dir <scratch>       # the A0 re-timing only

Start guards, all before anything is written (exit 2): a real run uses the pinned folders only (``--out-dir``
results/hold-mix-cap, ``--config-dir`` unset or config/, ``--catalog-dir`` data/catalog) and a dry run never writes
into results/hold-mix-cap or anywhere in the repo; ``--fast`` is for dry runs only; run 0 refuses an earlier run
folder (a real run 0: any results/hold-mix-cap/) and ``--amendment k`` refuses unless 1 <= k <= 2,
``run<k-1>/start.json`` exists, ``run<k>/`` does not, every earlier run is the same kind of run and (real data)
PLAN.md section 13 lists ``- **Amendment run k``; the RUNLOG must not hold this run number; a real run refuses a
dirty git tree and a catalog whose bars hash is not the pinned one; ``risk_limits("steady")`` must give both
``min_cash`` and ``max_coin`` and all the grid's mixes must pass ``check_targets`` with them; a real run whose A0
projection is above 240 CPU-minutes does not start (stop rule 9).

Then, before any bar is read: ``run<k>/start.json`` (the start record) and one RUNLOG line. Then the panels (row
counts, panel hashes on real data, every calendar window present), the grid in worker processes by (source, scope,
window) blocks, each block's rows written to ``run<k>/blocks/`` as it returns, the consistency stops of stop rule
8 (exit 3, recorded in ``summary.json``), and the outputs: ``runs.parquet``, ``limit_only_bands.parquet``,
``parity.parquet`` and ``failures.parquet`` (written before any count or decision, so a later stop or crash keeps
them), ``summary.json`` and ``decision.json`` in ``run<k>/``; the tracked ``RUNLOG.jsonl``, ``runs.csv``,
``falls.csv`` and ``decision.json`` in this folder (dry runs: ``<out>/tracked/``). ``decision.json`` carries the
boom-year addendum of PLAN.md A5 (``boom_check``). Exit codes: 0 done, 2 refused at start, 3 stopped by a guard or a
consistency stop.

The computations (the rule, the metrics, the decision rules) live in tested code, ``lab/runner/holdmix.py``. This
file holds the pinned values, the guards, the grid's bookkeeping and the outputs. ``research/`` is never imported by
``lab/``.
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
from lab.runner import portfolio as pf
from lab.runner.reference import Costs
from lab.runner.steady import panel_hash

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
SCRIPT = "run.py"
STUDY = "hold-mix-cap"
DEFAULT_OUT = REPO / "results" / STUDY
DEFAULT_CATALOG = REPO / "data" / "catalog"

INTERVAL = "1d"
LAST_CLOSE = H.LAST_CLOSE  # 2023-01-01 00:00 UTC, the last train close (section 3)
BARS_SHA256 = "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"  # section 3
PANEL_HASHES = {  # section 3: rebalance-steady run 0's panels, the same calls
    "KRAKEN": "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
    "BINANCE": "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
}
ROWS = {"KRAKEN": 2190, "BINANCE": 1963}  # section 3 (DATA.md)
MAX_AMENDMENTS = 2
CPU_MINUTES_MAX = 240.0  # section 11, stop rule 9
A0_REPS = 30
A0_REPS_FAST = 3
A0_CASES = ((0.5, 0.5, 0.20, 15, None), (0.78, 0.5, 0.05, 1, None), (0.2, 0.0, 0.50, 120, 365))  # section 11
REF = (H.REF_BOOK, "1x")
PARITY_F = (0.0, 0.5, 1.0)  # section 7: one absolute band for both coins (equal targets, or one coin)
BOOM_MIN_WINDOWS = H.BOOM_MIN_WINDOWS  # A5: a removal leaving a source fewer windows is MISSING
CONFIG_FILES = ("config/costs.yaml", "config/splits.yaml", "config/risk_levels.yaml")
LABEL = H.LABEL
STATUS = H.STATUS

INTERPRETATIONS = {
    "fast": "--fast is PLAN.md section 14's dry-run grid (3 mixes, 2 bands, 3 caps, 1 wallet size, both cost "
    "levels, 4 windows per source, with full runs and the other reading). It lacks the 6 bands, 7 caps and 3 wallet "
    "sizes the decision rules need, so a --fast run computes no decision. The grid in use is in start.json",
    "time": "A real run repeats A0 at start (30 repetitions; synthetic data only, no market bar) and refuses to start "
    "when the projection over the plan's grid is above 240 CPU-minutes (stop rule 9). Dry runs record it (3 "
    "repetitions with --fast) and never refuse on it",
    "dirty": "A dirty git tree (git status --porcelain --untracked-files=all prints anything) refuses real runs only",
    "run0": "A real run 0 refuses when results/hold-mix-cap/ exists; a dry run 0 refuses when <out>/run<j>/ exists",
    "same_kind_of_run": "--amendment k refuses unless every earlier run has the same data (real or synthetic) and "
    "--fast setting",
    "runlog": "A run number the RUNLOG already holds for the same data (any line, start or event) is refused. "
    "Besides the start line, an event line is appended when a run completes, stops or crashes",
    "stop_rule_3": "The loader is wrapped: a close after 2023-01-01 00:00 UTC stops the run before load_panel sees "
    "it (load_panel refuses it too). The incident is recorded in summary.json and the RUNLOG",
    "data_stops": "load_panel refusing the bars, a row count other than 2190 / 1963, another panel hash or snapshot "
    "(real data), or a calendar window whose closes are not all present: stop rule 5, before any backtest",
    "failures": "A run that raises (other than a consistency stop) is logged as failed with its error text, and the "
    "grid continues. decision.json is computed on the whole table (MISSING wherever a pool holds a failed run) and, "
    "in its rule_E block, on the table without the failed pairs: that block counts only if triage finds no code bug",
    "consistency": "Stop rule 8 in each run: holdmix.check_path (inside path_metrics) and the fee check of "
    "money_metrics; per configuration: one path hash over every cost setting; the parity checks; at the end: every "
    "count. Stop rule 10: the hashed files are hashed again at the end and must not have changed",
    "runs_csv": "One row per configuration and source. Each metric column M is the median over the windows "
    "(rolling) or the run's own value (full); M_tail is the 90th percentile (10th where smaller is worse) and "
    "M_worst the maximum (minimum where smaller is worse), rolling rows only. NaN values (no rebalance leg) are "
    "left out. Failed runs are left out and counted in n_failed",
    "falls": "falls.csv is holdmix.falls_tables at the robust headline (band, cap); with a MISSING headline it holds "
    "the header only",
    "per_share": "decision.json's per_share: at the robust headline (band, cap), per source and crypto share, over "
    "the rolling pairs at 5,000 USD and 1x (fees at each wallet size, 1x)",
    "kraken_on_binance_windows": "computed only when rule D's label is NOT ROBUST (section 9)",
    "parallel": "Workers are forked processes (multiprocessing 'fork'; start.json records the platform: fork is "
    "safe on Linux, where the real run is made); rows are sorted by a pinned key, so the outputs do not depend on "
    "the number of workers",
    "logging": "Stop rule 6 and section 12 (every run logged, nothing deleted): each block's four tables (runs, "
    "limit-only band rows, parity checks, failures) are written to run<k>/blocks/ as soon as the block returns, so a "
    "stop, a crash or a killed process keeps every block computed so far, and summary.json counts the blocks and "
    "runs logged. A block that stops is not written (its stop names the run); with 2 workers, blocks already running "
    "when another block stops finish and are written too. After the grid the four tables are written to run<k>/ "
    "before any count, check or decision, and runs.parquet is rewritten with the comparison columns",
    "parity_outcome": "A parity check compares the engine's own outcome (hold_mix's result or its refusal). A metric "
    "that fails after the engine ran makes a failed run (stop rule 4), never a failed parity check",
    "boom_check": "PLAN.md A5, an addendum next to the headline, never in its place: each train year 2017..2022 "
    "removed in turn, then the best one and two years by BTC's close-to-close calendar-year return on Kraken's "
    "closes (start.json year_returns, written right after the panels load, before any backtest). Every rolling "
    "window overlapping a removed year (by bar day) is dropped; rules B, A and C per source and rule D are "
    "recomputed on the logged runs of the kept windows; a removal leaving either source fewer than 12 windows is "
    "MISSING. With failed runs, rule E's block carries the same check on its kept pairs",
    "naive_index": "The stop rule 3 guard reads a loader's tz-naive index as UTC",
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
    return tuple(k for k, _, _ in H.rolling_windows(source))


@dataclass(frozen=True)
class Grid:
    """What a run covers. ``settings`` = every (wallet size, cost level); full runs use ``full_settings`` (None =
    ``settings``)."""

    mixes: tuple[tuple[float, float], ...]
    bands: tuple[float, ...]
    caps: tuple
    books: tuple[float, ...]
    costs: tuple[str, ...]
    windows: Mapping[str, tuple[int, ...]]
    full: bool = True
    full_resets: tuple = (None, H.RESET_DAYS)
    full_settings: tuple | None = None
    other_reading: bool = True
    name: str = "plan"

    @property
    def settings(self) -> tuple[tuple[float, str], ...]:
        return tuple((book, cost) for cost in self.costs for book in self.books)

    def scope_settings(self, scope: str) -> tuple[tuple[float, str], ...]:
        if scope == "full" and self.full_settings is not None:
            return tuple(self.full_settings)
        return self.settings

    @property
    def decidable(self) -> bool:
        return (
            tuple(self.bands) == H.BANDS
            and tuple(self.caps) == H.CAPS
            and tuple(self.books) == H.BOOKS
            and tuple(self.costs) == H.COST_LABELS
            and bool(self.mixes)
            and all(self.windows.get(s) for s in H.SOURCES)
        )

    def record(self) -> dict:
        return jsonable(
            {**asdict(self), "settings": self.settings, "decidable": self.decidable, "counts": expected_counts(self)}
        )


PLAN_GRID = Grid(
    mixes=tuple(H.MIXES),
    bands=H.BANDS,
    caps=H.CAPS,
    books=H.BOOKS,
    costs=H.COST_LABELS,
    windows={s: _all_windows(s) for s in H.SOURCES},
)
FAST = Grid(  # section 14: 3 mixes, 2 bands, 3 caps, 1 wallet size, both cost levels, 4 windows
    mixes=((0.5, 0.5), (0.3, 0.0), (0.78, 0.5)),
    bands=(0.10, 0.30),
    caps=(None, 2, 0.5),
    books=(H.REF_BOOK,),
    costs=H.COST_LABELS,
    windows={"KRAKEN": (0, 12, 26, 59), "BINANCE": (8, 20, 47, 59)},
    name="fast",
)


def _parity_mix(mix) -> bool:
    return mix[1] in PARITY_F


def expected_counts(grid: Grid) -> dict:
    """Section 11's counts for ``grid``: runs by kind and source, parity checks, limit-only band rows, runs.csv
    rows, and the runs by length (``runs_365``: rolling windows; ``runs_full``: full runs, parity checks included).
    For the plan's grid: 916,596 runs, 13,338 parity checks and 9,396 runs.csv rows."""
    nm, nb, nc = len(grid.mixes), len(grid.bands), len(grid.caps)
    finite = sum(c is not None for c in grid.caps)
    n_set, full_set = len(grid.settings), grid.scope_settings("full")
    has_ref = REF in grid.settings
    full_ref = grid.full and REF in full_set
    n_par = sum(_parity_mix(m) for m in grid.mixes)
    per = {}
    for source in H.SOURCES:
        w = len(grid.windows.get(source, ()))
        full = 1 if grid.full else 0
        lo_roll, lo_full = nm * n_set * w, nm * len(full_set) * full
        band_ok = None in grid.caps
        pb_roll = n_par * nb * w if has_ref and band_ok else 0
        pb_full = n_par * nb if full_ref and band_ok and None in grid.full_resets else 0
        pl_roll, pl_full = (nm * w if has_ref else 0), (nm if full_ref else 0)
        c = {
            "grid_rolling": nm * nb * nc * n_set * w,
            "grid_full": nm * nb * nc * len(grid.full_resets) * len(full_set) * full,
            "limit_only": lo_roll + lo_full,
            "other": nm * nb * finite * w if grid.other_reading and has_ref else 0,
            "parity_band": pb_roll + pb_full,
            "parity_limit": pl_roll + pl_full,
            "lob": (lo_roll + lo_full) * nb,
            "csv": nm * nb * ((nc + 1 if w else 0) + (nc * len(grid.full_resets) + 1) * full)
            + (nm * nb * finite if grid.other_reading and has_ref and w else 0),
        }
        c["runs_365"] = c["grid_rolling"] + c["other"] + lo_roll + pb_roll + pl_roll
        c["runs_full"] = c["grid_full"] + lo_full + pb_full + pl_full
        per[source] = c
    total = {key: sum(per[s][key] for s in H.SOURCES) for key in per[H.SOURCES[0]]}
    total["runs"] = sum(total[k] for k in ("grid_rolling", "grid_full", "limit_only", "other"))
    total["parity"] = total["parity_band"] + total["parity_limit"]
    return {"per_source": per, "total": total}


def pinned_values() -> dict:
    """The pinned values of the config hash (section 12)."""
    return jsonable(
        {
            "grid": {**asdict(PLAN_GRID), "settings": PLAN_GRID.settings},
            "windows": {s: H.rolling_windows(s) for s in H.SOURCES},
            "full_windows": {s: H.full_window(s) for s in H.SOURCES},
            "missing_closes": H.MISSING_CLOSES,
            "thresholds": thresholds(),
            "headroom": H.HEADROOM,
            "reading_grid": "lab (the first buy does not start the wait)",
            "reading_description": "other (the first buy starts the wait)",
            "limit_only_band": H.LIMIT_ONLY_BAND,
            "reset_days": H.RESET_DAYS,
            "boom": {
                "years": H.TRAIN_YEARS,
                "ranked_on": H.BOOM_RANK_SOURCE,
                "best": (1, 2),
                "min_windows": BOOM_MIN_WINDOWS,
            },
            "bars_sha256": BARS_SHA256,
            "panel_hashes": PANEL_HASHES,
            "rows": ROWS,
            "last_close": LAST_CLOSE,
        }
    )


def thresholds() -> dict:
    return {
        "EXTRA_OUT_MEDIAN": H.EXTRA_OUT_MEDIAN,
        "EXTRA_OUT_P90": H.EXTRA_OUT_P90,
        "RATE_MAX": H.RATE_MAX,
        "FEE_MAX": H.FEE_MAX,
        "CLOSE_SHARE": H.CLOSE_SHARE,
        "VALUE_FACTOR": H.VALUE_FACTOR,
    }


# ------------------------------------------------------------------------------------- hashing, git, json


def frozen_paths() -> list[str]:
    """The repo-relative files of the config hash (section 12), sorted."""
    fixed = [
        "research/hold-mix-cap/PLAN.md",
        "research/hold-mix-cap/run.py",
        "lab/runner/holdmix.py",
        "lab/runner/portfolio.py",
        "lab/runner/reference.py",
        "lab/runner/interface.py",
        "lab/runner/steady.py",
        "lab/data/panel.py",
        "lab/data/catalog.py",
        "lab/data/external.py",
        "lab/config.py",
        *CONFIG_FILES,
        "pyproject.toml",
        "uv.lock",
    ]
    globbed = [p.relative_to(REPO).as_posix() for p in (REPO / "lab" / "validation").glob("*.py")]
    return sorted(set(fixed) | set(globbed))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hashes(config_dir: Path | None = None) -> dict[str, str]:
    """SHA-256 of every hashed file; the three ``config/*.yaml`` files are read from ``config_dir`` (the files the
    run uses; default ``config/``) under their ``config/`` names."""
    cfg = Path(config_dir) if config_dir is not None else CONFIG_DIR
    return {
        rel: sha256_file(cfg / Path(rel).name if rel in CONFIG_FILES else REPO / rel) for rel in frozen_paths()
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


def runlog_path(out: Path, synthetic: bool) -> Path:
    """The tracked ``RUNLOG.jsonl`` for real runs; ``<out>/tracked/RUNLOG.jsonl`` for dry runs (section 12)."""
    return tracked_dir(out, synthetic) / "RUNLOG.jsonl"


def tracked_dir(out: Path, synthetic: bool) -> Path:
    """Where the tracked files go: this folder for real runs, ``<out>/tracked`` for dry runs."""
    return Path(out) / "tracked" if synthetic else HERE


def amendment_row_present(plan_text: str, k: int) -> bool:
    """PLAN.md section 13's list of amendments (from the line starting ``**Amendments.**`` to the line starting
    ``**Deviations.**``) holds a line starting with ``- **Amendment run k``."""
    start = re.search(r"^\*\*Amendments\.\*\*", plan_text, re.MULTILINE)
    end = re.search(r"^\*\*Deviations\.\*\*", plan_text, re.MULTILINE)
    if start is None or end is None or end.start() < start.start():
        return False
    pattern = re.compile(rf"^- \*\*Amendment run {k}\b", re.MULTILINE)
    return bool(pattern.search(plan_text[start.start() : end.start()]))


# ------------------------------------------------------------------------------------------- start guards


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path) -> None:
    """A dry run (or the timing) never writes into results/hold-mix-cap or anywhere in the repo (section 12)."""
    where = Path(out).resolve()
    if _inside(where, DEFAULT_OUT.resolve()) or _inside(where, REPO.resolve()):
        raise Refusal(
            f"--out-dir {out}: a synthetic dry run never writes into {DEFAULT_OUT} or inside the repo "
            "(PLAN.md section 12); use a scratch folder"
        )


def check_real_paths(out: Path, config_dir: Path | None, catalog_dir: Path) -> None:
    """A real run writes only to results/hold-mix-cap and reads only config/ and data/catalog/ (section 12)."""
    if Path(out).resolve() != DEFAULT_OUT.resolve():
        raise Refusal(f"--out-dir {out}: a real run writes only to {DEFAULT_OUT} (PLAN.md section 12)")
    if config_dir is not None and Path(config_dir).resolve() != (REPO / "config").resolve():
        raise Refusal(f"--config-dir {config_dir}: a real run reads config/ only (PLAN.md section 12)")
    if Path(catalog_dir).resolve() != DEFAULT_CATALOG.resolve():
        raise Refusal(f"--catalog-dir {catalog_dir}: a real run reads only {DEFAULT_CATALOG} (PLAN.md section 3)")


def check_layout(out: Path, k: int, synthetic: bool) -> None:
    """Stop rule 7's start refusals for run ``k`` (0 = run 0)."""
    out = Path(out)
    if k == 0:
        if not synthetic and out.exists():
            raise Refusal(f"{out} exists: run 0 runs once (stop rule 7). A rerun is --amendment k")
        if out.is_dir() and any(re.fullmatch(r"run\d+", p.name) for p in out.iterdir()):
            raise Refusal(f"{out} already holds a run folder: run 0 runs once (stop rule 7)")
        return
    if not 1 <= k <= MAX_AMENDMENTS:
        raise Refusal(
            f"--amendment {k}: amendment runs are numbered 1..{MAX_AMENDMENTS}. If a third would be needed, stop: "
            "no recommendation (stop rule 7)"
        )
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
                "number (stop rules 6-7)"
            )


def read_snapshot(catalog_dir: Path, synthetic: bool) -> dict:
    """``snapshot_id`` and ``bars_content_sha256`` from ``SNAPSHOT.json`` (metadata only, no bar). A real run
    refuses another bars hash (section 3). Dry runs read nothing."""
    if synthetic:
        return {"snapshot_id": "synthetic", "bars_content_sha256": "synthetic"}
    path = Path(catalog_dir) / catalog.SNAPSHOT_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read {path}: {exc}") from exc
    snap = {"snapshot_id": data.get("snapshot_id"), "bars_content_sha256": data.get("bars_content_sha256")}
    if snap["bars_content_sha256"] != BARS_SHA256:
        raise Refusal(
            f"the catalog's bars hash {snap['bars_content_sha256']!r} is not {BARS_SHA256} (PLAN.md section 3): "
            "stop and amend"
        )
    if not isinstance(snap["snapshot_id"], str) or not snap["snapshot_id"]:
        raise Refusal(f"{path} names no snapshot_id")
    return snap


def steady_limits(config_dir: Path | None) -> dict:
    """``portfolio.risk_limits("steady")``, refused unless it gives numbers for both ``min_cash`` and
    ``max_coin`` (section 4.2), and the grid's mixes checked against them with h = 0.02 (section 5)."""
    try:
        limits = pf.risk_limits("steady", config_dir)
    except (ValueError, OSError) as exc:
        raise Refusal(f"risk_limits('steady') does not read: {exc}") from exc
    if limits["min_cash"] is None or limits["max_coin"] is None:
        raise Refusal(
            f"the steady level must set both min_cash_pct and max_coin_pct (got min_cash {limits['min_cash']!r}, "
            f"max_coin {limits['max_coin']!r}): no run without a Steady limit (PLAN.md section 4.2)"
        )
    return limits


def check_mixes(mixes: Iterable, limits: Mapping) -> None:
    """Every mix of the grid in use must pass ``check_targets`` with the limits as read (section 5)."""
    try:
        H.check_grid(limits["min_cash"], limits["max_coin"], H.HEADROOM)
        for s, f in mixes:
            pf.check_targets(
                *H.mix_targets(s, f), min_cash=limits["min_cash"], max_coin=limits["max_coin"], headroom=H.HEADROOM
            )
    except ValueError as exc:
        raise Refusal(f"the Steady limits as read refuse the grid (PLAN.md section 5): {exc}") from exc


def cost_models(config_dir: Path | None, books: Iterable[float]) -> dict:
    """``Costs.from_yaml(capital_usd=V)`` (1x) and its ``stressed()`` (2x) for every wallet size, as read."""
    path = None if config_dir is None else Path(config_dir) / "costs.yaml"
    out = {}
    for book in books:
        base = Costs.from_yaml(path, capital_usd=float(book))
        out[(float(book), "1x")] = base
        out[(float(book), "2x")] = base.stressed()
    return out


# --------------------------------------------------------------------------------------------- the timing


def measure_throughput(limits: Mapping, config_dir: Path | None, reps: int) -> dict:
    """Section 11's A0 with the built code: ``hold_mix`` plus every metric on ``make_panel(synthetic_market(2190,
    seed=21, start="2017-01-02"))`` and its first 365 rows, three cases, ``reps`` repetitions (medians), and the
    projection over every run and parity check of the plan's grid (the slowest case at each length)."""
    panel = pf.make_panel(synthetic_market(2190, seed=21, start="2017-01-02"), snapshot_id="synthetic")
    costs = cost_models(config_dir, [H.REF_BOOK])[REF]
    cases = []
    for s, f, b, wait, reset in A0_CASES:
        targets = H.mix_targets(s, f)
        params = hold_params(targets, b, wait, reset, limits, first_buy_waits=False)
        for rows in (365, len(panel)):
            piece = panel.iloc[:rows]
            backtest, metrics = [], []
            for _ in range(reps):
                t0 = time.perf_counter()
                res = H.hold_mix(params, piece, costs)
                t1 = time.perf_counter()
                H.path_metrics(
                    res, targets=targets, band=b, min_cash=limits["min_cash"], max_coin=limits["max_coin"], wait=wait
                )
                H.trade_sizes(res)
                H.money_metrics(res, costs)
                H.path_hash(res)
                metrics.append(time.perf_counter() - t1)
                backtest.append(t1 - t0)
            cases.append(
                {
                    "case": [s, f, b, wait, reset],
                    "rows": rows,
                    "backtest_ms": 1e3 * float(np.median(backtest)),
                    "metrics_ms": 1e3 * float(np.median(metrics)),
                }
            )
    per = {
        rows: max(c["backtest_ms"] + c["metrics_ms"] for c in cases if c["rows"] == rows) / 1e3
        for rows in (365, len(panel))
    }
    n = expected_counts(PLAN_GRID)["total"]
    cpu_s = n["runs_365"] * per[365] + n["runs_full"] * per[len(panel)]
    return {
        "reps": reps,
        "cases": cases,
        "seconds_per_run": {str(k): v for k, v in per.items()},
        "runs_365": n["runs_365"],
        "runs_full": n["runs_full"],
        "cpu_minutes": cpu_s / 60.0,
        "wall_minutes_on_2_workers": cpu_s / 120.0,
        "limit_cpu_minutes": CPU_MINUTES_MAX,
        "python": sys.version.split()[0],
    }


# ------------------------------------------------------------------------------------------------ the data

SYNTHETIC_DAYS = 2191  # closes 2017-01-02 .. 2023-01-01, the Kraken grid of DATA.md
SYNTHETIC_FIRST = "2017-01-02"


def synthetic_bar_loader(seed: int) -> Callable:
    """A stand-in for ``lab.data.catalog.load_bars`` that serves SYNTHETIC daily bars on the plan's date grid, for
    dry runs and tests only: Kraken from close 2017-01-02 with ETH's 2018-01-13 bar missing; Binance from close
    2017-08-18 (the same bars times a small per-bar factor). Snapshot id ``"synthetic"``."""
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
        for missing in H.MISSING_CLOSES[source]:
            if asset == "ETH":
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
            latest = latest.tz_localize("UTC") if latest.tzinfo is None else latest  # a naive index read as UTC
            if latest > LAST_CLOSE:
                raise HoldoutWindowError(
                    f"{instrument}: the loader returned a close {latest.isoformat()} after the last train close "
                    f"{LAST_CLOSE.isoformat()}"
                )
        return frame

    return call


def load_study_panel(source: str, *, catalog_dir: Path, config_dir: Path | None, loader: Callable | None):
    """``load_panel(source, "1d", last_close=2023-01-01 00:00 UTC)`` through :func:`guarded`; a close after
    ``LAST_CLOSE`` is stop rule 3, any other refusal of the bars stop rule 5."""
    try:
        panel = load_panel(
            source, INTERVAL, last_close=LAST_CLOSE, catalog_dir=catalog_dir, config_dir=config_dir, loader=guarded(loader)
        )
    except HoldoutWindowError as exc:
        raise Stop("3", f"{source}: {exc}. Nothing from it is used; report the incident to the owner") from exc
    except ValueError as exc:
        raise Stop("5", f"load_panel refused the {source} bars: {exc}") from exc
    if panel.index.max() > LAST_CLOSE:
        raise Stop("3", f"{source}: a close after {LAST_CLOSE.isoformat()} was loaded")
    return panel


def panel_record(panel: pd.DataFrame) -> dict:
    """What start.json records of a loaded panel: rows, hash, first and last close, snapshot, missing and dropped
    closes."""
    return {
        "rows": len(panel),
        "hash": panel_hash(panel),
        "first": panel.index[0],
        "last": panel.index[-1],
        "snapshot_id": panel.attrs["snapshot_id"],
        "missing": panel.attrs["alignment"]["missing"]["closes"],
        "dropped": {a: panel.attrs["alignment"]["dropped"][a]["closes"] for a in pf.ASSETS},
    }


def check_panel(source: str, panel: pd.DataFrame, snapshot: Mapping, synthetic: bool) -> None:
    """Section 3's checks (stop rule 5): the row count, and on real data the panel hash and the snapshot id; then
    every calendar window (rolling and full) must hold exactly its closes (section 6)."""
    record = panel_record(panel)
    if len(panel) != ROWS[source]:
        raise Stop("5", f"{source}: {len(panel)} rows, expected {ROWS[source]} (PLAN.md section 3)")
    if not synthetic:
        if record["hash"] != PANEL_HASHES[source]:
            raise Stop("5", f"{source}: panel hash {record['hash']} is not {PANEL_HASHES[source]} (other bars)")
        if record["snapshot_id"] != snapshot["snapshot_id"]:
            raise Stop("5", f"{source}: panel snapshot {record['snapshot_id']!r} is not {snapshot['snapshot_id']!r}")
    for k, first, last in [*H.rolling_windows(source), (-1, *H.full_window(source))]:
        try:
            H.window_slice(panel, first, last, missing=H.MISSING_CLOSES[source])
        except H.WindowSliceError as exc:
            raise Stop("5", f"{source} window {k}: {exc}") from exc


# ------------------------------------------------------------------------------------- the runs of a block

PATH_KEYS = (
    "rows",
    "span_days",
    "wait_days",
    "rebalances",
    "rebalances_band",
    "rebalances_limit",
    "rebalances_reset",
    "rebalances_per_30d",
    "rebalances_per_30d_no_limit",
    "limit_in_wait",
    "limit_in_wait_per_year",
    "held",
    "held_per_year",
    "max_in_30d",
    "legs",
    "legs_per_year",
    "empty_orders",
    "in_band_share",
    "out_days_per_year",
    "longest_out_days",
    "dist_mean",
    "dist_worst",
    "drift_mean_pts",
    "drift_worst_pts",
    "breach_closes",
)
SIZE_KEYS = (
    "max_leg_pct",
    "max_day_turnover_pct",
    "min_leg_usd",
    "first_legs",
    "first_max_leg_pct",
    "first_turnover_pct",
    "first_min_leg_usd",
)
MONEY_KEYS = (
    "fees_pct_per_year",
    "gas_pct_per_year",
    "fees_usd_per_year",
    "gas_usd_per_year",
    "first_cost_pct",
    "first_cost_usd",
    "first_gas_usd",
    "total_return",
    "sharpe",
    "max_drawdown",
    "mdd_peak",
    "mdd_trough",
    "worst_day",
    "worst_day_close",
    "worst_week",
    "worst_week_start",
    "worst_week_end",
)
TIME_KEYS = ("first_close", "last_close", "mdd_peak", "mdd_trough", "worst_day_close", "worst_week_start", "worst_week_end")
BAND_KEYS = ("in_band_share", "out_days_per_year", "longest_out_days")
METRIC_KEYS = tuple(k for k in (*PATH_KEYS, *SIZE_KEYS, *MONEY_KEYS) if k not in TIME_KEYS and k != "rows")
RUN_COLUMNS = (
    "run_id",
    "source",
    "scope",
    "window",
    "first_close",
    "last_close",
    "comparator",
    "reading",
    "s",
    "f",
    "w_btc",
    "w_eth",
    "b",
    "cap",
    "W",
    "R",
    "V",
    "cost",
    "status",
    "error",
    "path_hash",
    *PATH_KEYS,
    *SIZE_KEYS,
    *MONEY_KEYS,
    "snapshot_id",
    "commit",
)
LOB_COLUMNS = (
    "run_id",
    "source",
    "scope",
    "window",
    "comparator",
    "reading",
    "s",
    "f",
    "b",
    "cap",
    "R",
    "V",
    "cost",
    "status",
    *BAND_KEYS,
)
PARITY_COLUMNS = ("kind", "source", "scope", "window", "s", "f", "b", "band_abs", "outcome")
FAILURE_COLUMNS = ("run_id", "source", "scope", "window", "error", "traceback")
CMP_METRICS = (
    "rebalances",
    "legs",
    "fees_pct_per_year",
    "gas_pct_per_year",
    "out_days_per_year",
    "dist_mean",
    "total_return",
    "sharpe",
    "max_drawdown",
)

_CTX: dict = {}


def hold_params(targets, band, wait, reset, limits, *, first_buy_waits: bool) -> dict:
    return {
        "w_btc": targets[0],
        "w_eth": targets[1],
        "band": float(band),
        "wait_days": int(wait),
        "min_cash": limits["min_cash"],
        "max_coin": limits["max_coin"],
        "headroom": H.HEADROOM,
        "reset_days": reset,
        "first_buy_waits": first_buy_waits,
    }


def run_id(source, scope, window, comparator, reading, s, f, b, cap, reset, book, cost) -> str:
    bb = "-" if b is None else format(float(b), "g")
    rr = "-" if reset is None else str(int(reset))
    return f"{source}:{scope}:{window}:{comparator}:{reading}:{s:g}:{f:g}:{bb}:{cap}:{rr}:{book:g}:{cost}"


def same_result(a, b) -> bool:
    """Bit for bit: index, every column, ``orders``, ``fills``, ``trade_returns``, ``n_trades``, ``snapshot_id``;
    or both refused with the same message (a fill costing the whole wallet)."""
    if isinstance(a, Exception) or isinstance(b, Exception):
        return isinstance(a, ValueError) and isinstance(b, ValueError) and str(a) == str(b)
    if not a.index.equals(b.index) or list(a.columns) != list(b.columns):
        return False
    for col in b.columns:
        if a[col].to_numpy(dtype="<f8").tobytes() != b[col].to_numpy(dtype="<f8").tobytes():
            return False
    for key in ("orders", "trade_returns"):
        if np.asarray(a.attrs[key]).tobytes() != np.asarray(b.attrs[key]).tobytes():
            return False
    return (
        a.attrs["n_trades"] == b.attrs["n_trades"]
        and a.attrs["snapshot_id"] == b.attrs["snapshot_id"]
        and a.attrs["fills"].equals(b.attrs["fills"])
    )


def _run_configuration(piece, base: dict, params: dict, settings, *, metric_band: float, wait: int, other: bool):
    """One configuration at each cost setting: the runs' rows, their results (an exception for a failed run), the
    failures and the engine's own outcomes (``hold_mix``'s result, or its exception: what the parity checks compare).
    A ConsistencyError (check_path, the fee check) or path hashes that differ between the settings stop the run."""
    ctx = _CTX
    rows, results, failures, hashes, engine = [], {}, [], {}, {}
    for book, cost in settings:
        costs = ctx["costs"][(book, cost)]
        rid = run_id(
            base["source"], base["scope"], base["window"], base["comparator"], base["reading"], base["s"], base["f"],
            None if math.isnan(base["b"]) else base["b"], base["cap"], params["reset_days"], book, cost,
        )
        row = {**base, "run_id": rid, "V": float(book), "cost": cost, "status": H.OK, "error": "", "path_hash": ""}
        try:
            try:
                res = engine[(book, cost)] = H.hold_mix(params, piece, costs)
            except Exception as exc:
                engine[(book, cost)] = exc
                raise
            pm = H.path_metrics(
                res,
                targets=(params["w_btc"], params["w_eth"]),
                band=metric_band,
                min_cash=params["min_cash"],
                max_coin=params["max_coin"],
                wait=wait,
                first_buy_waits=other,
            )
            sizes = H.trade_sizes(res)
            money = H.money_metrics(res, costs)
        except H.ConsistencyError as exc:
            raise Stop("8", f"{rid}: {exc}") from exc
        except Exception as exc:  # a failed run is logged and the grid continues (stop rule 4)
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            failures.append(
                {
                    "run_id": rid,
                    "source": base["source"],
                    "scope": base["scope"],
                    "window": base["window"],
                    "error": row["error"],
                    "traceback": traceback.format_exc(),
                }
            )
            results[(book, cost)] = exc
        else:
            row.update(pm)
            row.update(sizes)
            row.update(money)
            row["path_hash"] = hashes[(book, cost)] = H.path_hash(res)
            results[(book, cost)] = res
        rows.append(row)
    if len(set(hashes.values())) > 1:
        raise Stop(
            "8",
            f"{rows[0]['run_id']}: the path hash differs between cost settings {sorted(hashes, key=str)} "
            "(section 4.6)",
        )
    return rows, results, failures, engine


def _parity(kind, base, b, band_abs, mine, params, piece, limits) -> dict:
    """Section 7's parity check against ``portfolio.rebalance(band = band_abs, every = 1)`` at 5,000 USD and 1x."""
    costs = _CTX["costs"][REF]
    rp = {
        "w_btc": params["w_btc"],
        "w_eth": params["w_eth"],
        "band": band_abs,
        "every": 1,
        "min_cash": limits["min_cash"],
        "max_coin": limits["max_coin"],
        "headroom": H.HEADROOM,
    }
    try:
        theirs = pf.rebalance(rp, piece, costs)
    except ValueError as exc:
        theirs = exc
    if not same_result(mine, theirs):
        raise Stop(
            "8",
            f"parity ({kind}) fails: {base['source']} {base['scope']} window {base['window']} mix ({base['s']}, "
            f"{base['f']}) band {b} against portfolio.rebalance(band = {band_abs!r}, every = 1) (section 7)",
        )
    return {
        "kind": kind,
        "source": base["source"],
        "scope": base["scope"],
        "window": base["window"],
        "s": base["s"],
        "f": base["f"],
        "b": b,
        "band_abs": band_abs,
        "outcome": "both refused alike" if isinstance(mine, Exception) else "equal",
    }


def _block(source: str, scope: str, k: int) -> dict:
    ctx = _CTX
    grid: Grid = ctx["grid"]
    limits = ctx["limits"]
    first, last = H.full_window(source) if scope == "full" else dict((w, (a, z)) for w, a, z in H.rolling_windows(source))[k]
    try:
        piece = H.window_slice(ctx["panels"][source], first, last, missing=H.MISSING_CLOSES[source])
    except H.WindowSliceError as exc:
        raise Stop("5", f"{source} {scope} window {k}: {exc}") from exc
    settings = grid.scope_settings(scope)
    resets = grid.full_resets if scope == "full" else (None,)
    rows, lob, parity, failures = [], [], [], []
    common = {
        "rows": len(piece),
        "source": source,
        "scope": scope,
        "window": k,
        "first_close": first,
        "last_close": last,
        "snapshot_id": ctx["snapshot_id"],
        "commit": ctx["commit"],
    }
    for s, f in grid.mixes:
        targets = H.mix_targets(s, f)
        mix = {**common, "s": float(s), "f": float(f), "w_btc": targets[0], "w_eth": targets[1]}
        for b in grid.bands:
            for cap in grid.caps:
                wait = H.wait_days(cap)
                for reset in resets:
                    base = {
                        **mix,
                        "comparator": "grid",
                        "reading": "lab",
                        "b": float(b),
                        "cap": H.cap_label(cap),
                        "W": wait,
                        "R": math.nan if reset is None else float(reset),
                    }
                    params = hold_params(targets, b, wait, reset, limits, first_buy_waits=False)
                    got, _, fails, engine = _run_configuration(piece, base, params, settings, metric_band=b, wait=wait, other=False)
                    rows += got
                    failures += fails
                    if cap is None and reset is None and _parity_mix((s, f)) and REF in engine:
                        band_abs = float(b) * max(targets)
                        parity.append(_parity("band", base, float(b), band_abs, engine[REF], params, piece, limits))
                if scope == "rolling" and grid.other_reading and cap is not None and REF in grid.settings:
                    base = {
                        **mix,
                        "comparator": "grid",
                        "reading": "other",
                        "b": float(b),
                        "cap": H.cap_label(cap),
                        "W": wait,
                        "R": math.nan,
                    }
                    params = hold_params(targets, b, wait, None, limits, first_buy_waits=True)
                    got, _, fails, _ = _run_configuration(piece, base, params, (REF,), metric_band=b, wait=wait, other=True)
                    rows += got
                    failures += fails
        # limit-only (section 7): the band never fires, W = 1, no reset
        base = {**mix, "comparator": "limit-only", "reading": "lab", "b": math.nan, "cap": "none", "W": 1, "R": math.nan}
        params = hold_params(targets, H.LIMIT_ONLY_BAND, 1, None, limits, first_buy_waits=False)
        got, results, fails, engine = _run_configuration(piece, base, params, settings, metric_band=H.LIMIT_ONLY_BAND, wait=1, other=False)
        failures += fails
        for row in got:
            res = results[(row["V"], row["cost"])]
            for b in grid.bands:
                band_row = {key: row[key] for key in LOB_COLUMNS if key not in BAND_KEYS and key != "b"}
                band_row["b"] = float(b)
                if isinstance(res, Exception):
                    band_row.update(dict.fromkeys(BAND_KEYS, math.nan))
                else:
                    try:
                        pm = H.path_metrics(
                            res, targets=targets, band=b, min_cash=limits["min_cash"], max_coin=limits["max_coin"], wait=1
                        )
                    except H.ConsistencyError as exc:
                        raise Stop("8", f"{row['run_id']} at band {b}: {exc}") from exc
                    band_row.update({key: pm[key] for key in BAND_KEYS})
                lob.append(band_row)
            row.update(dict.fromkeys(BAND_KEYS, math.nan))  # measured per band in limit_only_bands
        rows += got
        if REF in engine:
            parity.append(_parity("limit-only", base, math.nan, 1.0, engine[REF], params, piece, limits))
    return {
        "runs": _frame(rows, RUN_COLUMNS),
        "lob": _frame(lob, LOB_COLUMNS),
        "parity": pd.DataFrame(parity, columns=list(PARITY_COLUMNS)),
        "failures": pd.DataFrame(failures, columns=list(FAILURE_COLUMNS)),
    }


def _frame(rows: list[dict], columns: Sequence[str]) -> pd.DataFrame:
    """Rows to a frame with stable dtypes, whatever failed: timestamps as UTC microseconds, metrics as float64."""
    frame = pd.DataFrame(rows, columns=list(columns))
    for col in frame.columns:
        if col in TIME_KEYS:
            frame[col] = pd.to_datetime(frame[col], utc=True).astype("datetime64[us, UTC]")
        elif col in METRIC_KEYS or col in ("s", "f", "w_btc", "w_eth", "b", "R", "V"):
            frame[col] = frame[col].astype("float64")
        elif col in ("window", "W", "rows"):
            frame[col] = frame[col].astype("int64")
    return frame


def run_block(task: tuple) -> dict:
    """One (source, scope, window) block in a worker, with its ``task``; a stop comes back as ``{"stop": (rule,
    message)}``."""
    try:
        return {**_block(*task), "task": task}
    except Stop as exc:
        return {"stop": (exc.rule, str(exc).split(": ", 1)[1]), "task": task}


def _init_worker(ctx: dict) -> None:
    _CTX.clear()
    _CTX.update(ctx)


def tasks(grid: Grid) -> list[tuple]:
    out = []
    for source in H.SOURCES:
        out += [(source, "rolling", k) for k in grid.windows.get(source, ())]
        if grid.full:
            out.append((source, "full", -1))
    return out


def run_blocks(ctx: dict, workers: int, on_result: Callable[[dict], None] | None = None) -> list[dict]:
    """Every block, in task order, on ``workers`` processes (forked; 1 = this process). ``on_result`` sees each
    block as it returns (the logging). After a stop no new block starts; with workers, the blocks already running
    finish and are returned (and seen) after the stopping one, in task order."""
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
    ) as pool:
        futures = [pool.submit(run_block, task) for task in todo]
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

SOURCE_ORDER = {s: i for i, s in enumerate(H.SOURCES)}
SCOPE_ORDER = {"rolling": 0, "full": 1}
COMPARATOR_ORDER = {"grid": 0, "limit-only": 1}
READING_ORDER = {"lab": 0, "other": 1}
CAP_ORDER = {c: i for i, c in enumerate(H.CAP_LABELS)}
COST_ORDER = {c: i for i, c in enumerate(H.COST_LABELS)}


def sort_rows(frame: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """Rows in the pinned order: source, scope, window, comparator, reading, s, f, b (none last), cap (none
    first, then tightest last as CAP_LABELS lists them), R (none first), V, cost, as present in ``keys``."""
    order = {
        "source": SOURCE_ORDER,
        "scope": SCOPE_ORDER,
        "comparator": COMPARATOR_ORDER,
        "reading": READING_ORDER,
        "cap": CAP_ORDER,
        "cost": COST_ORDER,
    }
    helper = {}
    for key in keys:
        if key in order:
            helper[f"_k_{key}"] = frame[key].map(order[key]).to_numpy()
        elif key in ("b", "R"):
            col = frame[key].to_numpy(dtype=float)
            helper[f"_k_{key}"] = np.where(np.isnan(col), np.inf if key == "b" else -np.inf, col)
        else:
            helper[f"_k_{key}"] = frame[key].to_numpy()
    tmp = frame.assign(**helper).sort_values(list(helper), kind="stable")
    return tmp.drop(columns=list(helper)).reset_index(drop=True)


RUN_SORT = ("source", "scope", "window", "comparator", "reading", "s", "f", "b", "cap", "R", "V", "cost")
LOB_SORT = (*RUN_SORT[:-1], "cost")


def add_comparisons(runs: pd.DataFrame, lob: pd.DataFrame) -> pd.DataFrame:
    """Section 8's comparisons: each grid run minus the no-cap run (the lab's reading) and minus the limit-only run
    of the same mix, window, wallet size and costs (``vs_nocap_*``, ``vs_limit_*``; D_out against limit-only at the
    run's band). NaN where there is no comparator, and for limit-only rows."""
    key = ["source", "scope", "window", "s", "f", "V", "cost"]
    r_key = runs["R"].fillna(-1.0)
    grid = runs["comparator"].to_numpy() == "grid"
    nocap = runs[grid & (runs["reading"].to_numpy() == "lab") & (runs["cap"].to_numpy() == "none")]
    ref = nocap.assign(_R=r_key[nocap.index])[[*key, "b", "_R", *CMP_METRICS]]
    left = runs.assign(_R=r_key)[[*key, "b", "_R"]]
    merged = left.merge(ref, on=[*key, "b", "_R"], how="left", validate="many_to_one")
    lim = runs[~grid][[*key, *CMP_METRICS]]
    merged_l = left.merge(lim, on=key, how="left", validate="many_to_one")
    lob_d = lob.rename(columns={"out_days_per_year": "_d_lo"})[[*key, "b", "_d_lo"]]
    merged_d = left.merge(lob_d, on=[*key, "b"], how="left", validate="many_to_one")
    out = runs.copy()
    for m in CMP_METRICS:
        mine = runs[m].to_numpy(dtype=float)
        out[f"vs_nocap_{m}"] = np.where(grid, mine - merged[m].to_numpy(dtype=float), np.nan)
        other = merged_d["_d_lo"].to_numpy(dtype=float) if m == "out_days_per_year" else merged_l[m].to_numpy(dtype=float)
        out[f"vs_limit_{m}"] = np.where(grid, mine - other, np.nan)
    return out


ONCE_METRICS = (
    "rebalances_per_30d",
    "rebalances_per_30d_no_limit",
    "rebalances_band",
    "rebalances_limit",
    "rebalances_reset",
    "limit_in_wait_per_year",
    "held_per_year",
    "max_in_30d",
    "legs_per_year",
    "empty_orders",
    "in_band_share",
    "out_days_per_year",
    "longest_out_days",
    "dist_mean",
    "dist_worst",
    "drift_mean_pts",
    "drift_worst_pts",
    "breach_closes",
    "max_leg_pct",
    "max_day_turnover_pct",
    "first_max_leg_pct",
    "first_turnover_pct",
)
SETTING_METRICS = (
    "fees_pct_per_year",
    "gas_pct_per_year",
    "fees_usd_per_year",
    "gas_usd_per_year",
    "min_leg_usd",
    "first_cost_pct",
    "first_min_leg_usd",
)
SMALLER_WORSE = frozenset({"in_band_share", "min_leg_usd", "first_min_leg_usd"})
CSV_KEYS = ("label", "source", "scope", "comparator", "reading", "s", "f", "w_btc", "w_eth", "b", "cap", "W", "R")


def setting_tag(book: float, cost: str) -> str:
    return f"{book:g}_{cost}"


def _stat_columns(metric: str) -> list[str]:
    return [metric, f"{metric}_tail", f"{metric}_worst"]


CSV_COLUMNS = (
    *CSV_KEYS,
    "n_windows",
    "n_failed",
    *(c for m in ONCE_METRICS for c in _stat_columns(m)),
    *(c for st in PLAN_GRID.settings for m in SETTING_METRICS for c in _stat_columns(f"{m}_{setting_tag(*st)}")),
)
FORBIDDEN_CSV = ("total_return", "sharpe", "max_drawdown", "worst_day", "worst_week", "mdd_")


def _aggregate(frame: pd.DataFrame, keys: list[str], metrics: Sequence[str], rename: Callable[[str], str]) -> pd.DataFrame:
    """Per group: the median of each metric (rolling) or the run's own value (full: one run), and for rolling groups
    the bad tail and the worst; NaN values left out (INTERPRETATIONS["runs_csv"])."""
    g = frame.groupby(keys, sort=False, dropna=False)
    out = {}
    rolling = frame["scope"].iloc[0] == "rolling" if len(frame) else True
    for m in metrics:
        smaller = m in SMALLER_WORSE
        name = rename(m)
        out[name] = g[m].median()
        if rolling:
            out[f"{name}_tail"] = g[m].quantile(0.1 if smaller else 0.9)
            out[f"{name}_worst"] = g[m].min() if smaller else g[m].max()
    return pd.DataFrame(out)


def runs_csv(runs: pd.DataFrame, lob: pd.DataFrame) -> pd.DataFrame:
    """The tracked ``runs.csv`` (section 12): one row per configuration and source, with the columns of
    :data:`CSV_COLUMNS` (no return, Sharpe, drawdown or worst day), sorted by the pinned key."""
    parts = []
    runs = runs.assign(R=runs["R"].fillna(-1.0))  # a group key: no NaN in the index (restored below)
    for scope in ("rolling", "full"):
        sc = runs[runs["scope"].to_numpy() == scope]
        for comparator in ("grid", "limit-only"):
            part = sc[sc["comparator"].to_numpy() == comparator]
            if part.empty:
                continue
            if comparator == "grid":
                keys = ["source", "scope", "comparator", "reading", "s", "f", "w_btc", "w_eth", "b", "cap", "W", "R"]
                base = part
            else:  # one row per band: the band metrics from limit_only_bands, the rest from the runs
                keys = ["source", "scope", "comparator", "reading", "s", "f", "w_btc", "w_eth", "b", "cap", "W", "R"]
                bands = sorted(set(lob["b"]))
                base = pd.concat([part.assign(b=b) for b in bands], ignore_index=True)
                lo = lob[lob["scope"].to_numpy() == scope][["run_id", "b", *BAND_KEYS]]
                base = base.drop(columns=list(BAND_KEYS)).merge(lo, on=["run_id", "b"], how="left", validate="one_to_one")
            ok = base[base["status"].to_numpy() == H.OK]
            counts = base.groupby(keys, sort=False, dropna=False).agg(
                n_windows=("window", "nunique"), n_failed=("status", lambda x: int((x != H.OK).sum()))
            )
            ref = ok[(ok["V"].to_numpy() == REF[0]) & (ok["cost"].to_numpy() == REF[1])]
            table = counts.join(_aggregate(ref, keys, ONCE_METRICS, lambda m: m), how="left")
            for st in PLAN_GRID.settings:
                at = ok[(ok["V"].to_numpy() == st[0]) & (ok["cost"].to_numpy() == st[1])]
                if at.empty:
                    continue
                tag = setting_tag(*st)
                table = table.join(_aggregate(at, keys, SETTING_METRICS, lambda m, tag=tag: f"{m}_{tag}"), how="left")
            parts.append(table.reset_index())
    table = pd.concat(parts, ignore_index=True)
    table["R"] = table["R"].where(table["R"].to_numpy() != -1.0, np.nan)
    table["label"] = LABEL
    table = table.reindex(columns=list(CSV_COLUMNS))
    return sort_rows(table, ("source", "scope", "comparator", "reading", "s", "f", "b", "cap", "R"))


def csv_text(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, float_format="%.6g", lineterminator="\n")


# ------------------------------------------------------------------------------------------ the decisions


def per_share(runs: pd.DataFrame, headline: Mapping) -> dict | None:
    """At the headline (band, cap), per source and crypto share, over the rolling pairs of the pool at 5,000 USD
    and 1x: the most rebalances in any 30 days, limit fixes included (median and worst), the rebalance rates with
    and without limit fixes, limit fixes inside the wait, D_out, and the median fees at each wallet size (1x)."""
    band, cap = headline["band"], headline["cap"]
    if band == H.MISSING or cap == H.MISSING:
        return None
    out = {}
    for source in H.SOURCES:
        p = H.pool(runs, source)
        at = p[(p["b"].to_numpy() == band) & (p["cap"].to_numpy() == cap)]
        rows = []
        for s in sorted(set(at["s"])):
            mine = at[at["s"].to_numpy() == s]
            ref = mine[(mine["V"].to_numpy() == REF[0]) & (mine["cost"].to_numpy() == REF[1])]
            if (mine["status"].to_numpy() != H.OK).any():
                rows.append({"s": s, "status": H.MISSING})
                continue
            rows.append(
                {
                    "s": s,
                    "pairs": len(ref),
                    "max_in_30d_median": float(np.median(ref["max_in_30d"])),
                    "max_in_30d_worst": float(ref["max_in_30d"].max()),
                    "rebalances_per_30d_median": float(np.median(ref["rebalances_per_30d"])),
                    "rebalances_per_30d_no_limit_median": float(np.median(ref["rebalances_per_30d_no_limit"])),
                    "limit_in_wait_per_year_median": float(np.median(ref["limit_in_wait_per_year"])),
                    "limit_in_wait_per_year_worst": float(ref["limit_in_wait_per_year"].max()),
                    "out_days_per_year_median": float(np.median(ref["out_days_per_year"])),
                    "fees_pct_per_year_median_1x": {
                        book: float(
                            np.median(
                                mine.loc[
                                    (mine["V"].to_numpy() == book) & (mine["cost"].to_numpy() == "1x"),
                                    "fees_pct_per_year",
                                ]
                            )
                        )
                        for book in sorted(set(mine["V"]))
                    },
                }
            )
        out[source] = rows
    return out


def decide_sources(runs: pd.DataFrame, lob: pd.DataFrame, windows: Mapping | None = None) -> dict:
    """Rules B, A and C per source (``holdmix.decide_source``), optionally on some windows only."""
    out = {}
    for source in H.SOURCES:
        p, lo, lb = H.pool(runs, source), H.limit_only_pool(runs, source), H.limit_only_pool(lob, source)
        if windows is not None:
            keep = list(windows[source])
            p, lo, lb = (x[x["window"].isin(keep).to_numpy()] for x in (p, lo, lb))
        out[source] = H.decide_source(p, lo, limit_only_bands=lb)
    return out


RULE_COLUMNS = (
    *H.RUN_KEYS,
    "status",
    "out_days_per_year",
    "rebalances_per_30d",
    "fees_pct_per_year",
    "dist_mean",
    "gas_usd_per_year",
)


def plain(frame: pd.DataFrame) -> pd.DataFrame:
    """A copy whose text columns are plain Python objects: the rules compare columns to a value hundreds of times,
    and pandas' string columns convert on each comparison (about twice as slow; the results are the same)."""
    out = frame.copy()
    for col in out.columns:
        if out[col].dtype.kind not in "biufcmM":
            out[col] = out[col].astype(object)
    return out


def narrow(runs: pd.DataFrame) -> pd.DataFrame:
    """The columns the decision rules read, as :func:`plain` (the rules filter the table many times)."""
    return plain(runs[list(RULE_COLUMNS)])


def boom_check(runs: pd.DataFrame, lob: pd.DataFrame, returns: Mapping, headline: Mapping) -> dict:
    """PLAN.md A5, the boom-year addendum: for each removal (``holdmix.boom_plan`` on the ranking source's yearly
    ``returns``, over the windows each source's decision pool holds in ``runs``), rules B, A and C per source and
    rule D on the kept windows (:func:`decide_sources`, ``holdmix.robust``), and whether each headline value of
    ``headline`` (rule D's output on every window) is kept (``holdmix.boom_compare``). A removal that leaves a source
    fewer than ``BOOM_MIN_WINDOWS`` windows is MISSING. Never replaces the headline."""
    windows = {source: sorted(set(H.pool(runs, source)["window"].tolist())) for source in H.SOURCES}
    removals = []
    for entry in H.boom_plan(returns[H.BOOM_RANK_SOURCE], windows, min_windows=BOOM_MIN_WINDOWS):
        entry = {**entry, "robust": None, "same_as_headline": None}
        if entry["status"] == H.OK:
            bundles = decide_sources(runs, lob, windows=entry["windows"])
            entry["robust"] = H.robust(bundles["KRAKEN"], bundles["BINANCE"])
            entry["same_as_headline"] = H.boom_compare(headline, entry["robust"])
        removals.append(entry)
    return {
        "label": H.BOOM_LABEL,
        "status": STATUS,
        "ranked_on": H.BOOM_RANK_SOURCE,
        "year_returns": returns,
        "min_windows": BOOM_MIN_WINDOWS,
        "removals": removals,
    }


def decisions(runs: pd.DataFrame, lob: pd.DataFrame, grid: Grid, returns: Mapping) -> dict:
    """Section 9, applied mechanically: rules B, A and C per source, rule D, the descriptions, the per-share table,
    (NOT ROBUST) Kraken on Binance's windows, and the boom-year addendum of A5 (``returns``: each source's BTC
    calendar-year returns, from start.json)."""
    full_table, runs, lob = runs, narrow(runs), plain(lob)
    bundles = decide_sources(runs, lob)
    rob = H.robust(bundles["KRAKEN"], bundles["BINANCE"])
    kob = None
    if rob["label"] == H.NOT_ROBUST:
        shared = sorted(set(grid.windows["KRAKEN"]) & set(grid.windows["BINANCE"]))
        if shared:
            p = H.pool(runs, "KRAKEN")
            p = p[p["window"].isin(shared).to_numpy()]
            lo = H.limit_only_pool(runs, "KRAKEN")
            lo = lo[lo["window"].isin(shared).to_numpy()]
            lb = H.limit_only_pool(lob, "KRAKEN")
            lb = lb[lb["window"].isin(shared).to_numpy()]
            kob = {"windows": shared, "decisions": H.decide_source(p, lo, limit_only_bands=lb)}
    return {
        "sources": bundles,
        "robust": rob,
        "kraken_on_binance_windows": kob,
        "descriptions": H.descriptions(runs, runs, limit_only_bands=lob),
        "per_share": per_share(full_table, rob["headline"]),
        "boom_check": boom_check(runs, lob, returns, rob),
    }


def rule_e(runs: pd.DataFrame, lob: pd.DataFrame, returns: Mapping) -> dict:
    """Rule E's block: the failed runs, the pairs dropped, and rules A-D and the boom-year addendum (A5) on the rest
    (valid only if triage finds no code bug)."""
    kept, dropped = H.drop_failed_pairs(narrow(runs))
    lob = plain(lob)
    keys = ["source", "scope", "window", "s", "f"]
    hit = pd.MultiIndex.from_frame(lob[keys]).isin(dropped) if dropped else np.zeros(len(lob), dtype=bool)
    out = {"failed_runs": int((runs["status"].to_numpy() != H.OK).sum()), "dropped_pairs": dropped}
    try:
        bundles = decide_sources(kept, lob[~hit])
        out["sources"] = bundles
        out["robust"] = H.robust(bundles["KRAKEN"], bundles["BINANCE"])
        out["boom_check"] = boom_check(kept, lob[~hit], returns, out["robust"])
    except ValueError as exc:
        out["error"] = f"cannot apply the rules to the kept pairs: {exc}"
    return out


# ------------------------------------------------------------------------------------------------ the run


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT), help="results folder (default results/hold-mix-cap)")
    ap.add_argument("--catalog-dir", default=str(DEFAULT_CATALOG))
    ap.add_argument("--config-dir", default=None, help="folder with costs.yaml, splits.yaml, risk_levels.yaml")
    ap.add_argument("--amendment", type=int, default=None, metavar="K", help="amendment run K (1 or 2)")
    ap.add_argument("--workers", type=int, default=2, help="worker processes (default 2)")
    ap.add_argument("--synthetic", type=int, default=None, metavar="SEED", help="dry run on synthetic bars")
    ap.add_argument("--fast", action="store_true", help="dry runs only: section 14's small grid")
    ap.add_argument("--time", action="store_true", help="only the A0 re-timing, into --out-dir (a scratch folder)")
    return ap.parse_args(argv)


def timing_only(args) -> int:
    if args.synthetic is not None or args.amendment is not None or args.fast:
        raise Refusal("--time runs on its own (with --out-dir and optionally --config-dir)")
    out = Path(args.out_dir)
    check_out_dir(out)
    config_dir = Path(args.config_dir) if args.config_dir else None
    limits = steady_limits(config_dir)
    timing = measure_throughput(limits, config_dir, A0_REPS)
    write_json(out / "timing.json", {"utc": utc_now(), "label": LABEL, "timing": timing})
    print(
        f"A0 re-timing: {timing['cpu_minutes']:.1f} CPU-minutes for the plan's grid (limit {CPU_MINUTES_MAX:g}); "
        f"about {timing['wall_minutes_on_2_workers']:.1f} minutes on 2 workers. Written to {out / 'timing.json'}",
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
        raise Refusal(f"--amendment {k}: PLAN.md section 13 lists no '- **Amendment run {k}' row (stop rule 7)")
    git = git_state()
    if git["dirty"] and not synthetic:
        raise Refusal(
            "the git tree is dirty (git status --porcelain --untracked-files=all): commit first (stop rule 2). "
            f"Changes: {git['changes'][:10]}"
        )
    hashes = file_hashes(config_dir)
    snapshot = read_snapshot(catalog_dir, synthetic)
    limits = steady_limits(config_dir)
    grid = FAST if args.fast else PLAN_GRID
    check_mixes(grid.mixes, limits)
    costs = cost_models(config_dir, sorted(set(grid.books) | {H.REF_BOOK}))
    try:
        timing = measure_throughput(limits, config_dir, A0_REPS_FAST if args.fast else A0_REPS)
    except Exception as exc:  # the engine fails on the timing's synthetic panel: nothing can run
        raise Refusal(f"the A0 re-timing failed (section 11): {type(exc).__name__}: {exc}") from exc
    if not synthetic and timing["cpu_minutes"] > CPU_MINUTES_MAX:
        raise Refusal(
            f"stop rule 9: the A0 projection is {timing['cpu_minutes']:.1f} CPU-minutes, above "
            f"{CPU_MINUTES_MAX:g}: amend the grid (PLAN.md section 11) before any run"
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


def costs_record(costs: Mapping) -> dict:
    return {setting_tag(*key): asdict(value) for key, value in sorted(costs.items(), key=lambda kv: (kv[0][1], kv[0][0]))}


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
        "costs": costs_record(g["costs"]),
        "grid": grid.record(),
        "windows": {s: H.rolling_windows(s) for s in H.SOURCES},
        "full_windows": {s: H.full_window(s) for s in H.SOURCES},
        "thresholds": thresholds(),
        "headroom": H.HEADROOM,
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
    summary = {"study": STUDY, "run": k, "data": g["data"], "status": "started", "label": LABEL, "scouting_status": STATUS}
    write_json(run_dir / "summary.json", summary)
    print(f"run {k} ({g['data']}, grid {grid.name}) started; config hash {start['config_hash'][:16]}", flush=True)
    t0 = time.time()

    def end(status: str, event: str, **extra) -> None:
        summary.update(status=status, runtime_s=time.time() - t0, **extra)
        write_json(run_dir / "summary.json", summary)
        append_runlog(log, {"utc": utc_now(), "script": SCRIPT, "run": k, "data": g["data"], "event": event})

    try:
        results = study(args, g, start, run_dir, summary)
        if file_hashes(g["config_dir"]) != g["hashes"]:
            raise Stop("10", "a hashed file changed during the run (PLAN.md section 13)")
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
        f"run {k} complete in {time.time() - t0:.1f}s: {results['summary']['counts']['runs']} runs, "
        f"{results['summary']['failed_runs']} failed; headline {results['summary']['headline']}",
        flush=True,
    )
    return 0


def study(args, g: dict, start: dict, run_dir: Path, summary: dict) -> dict:
    """From the panels to the tables. Written here: start.json (the panels, then the yearly returns), summary.json,
    each block's tables in blocks/ as it returns, and the four tables before any count, check or decision
    (INTERPRETATIONS["logging"]); decision.json and the tracked files come later (write_outputs)."""
    loader = synthetic_bar_loader(args.synthetic) if g["synthetic"] else None
    panels = {}
    for source in H.SOURCES:
        panels[source] = load_study_panel(
            source, catalog_dir=g["catalog_dir"], config_dir=g["config_dir"], loader=loader
        )
    start["panels"] = {source: panel_record(panels[source]) for source in H.SOURCES}  # before any check
    write_json(run_dir / "start.json", start)
    returns = {source: H.year_returns(panels[source]) for source in H.SOURCES}  # A5's ranking, before any backtest
    start["year_returns"] = returns
    write_json(run_dir / "start.json", start)
    for source in H.SOURCES:
        check_panel(source, panels[source], g["snapshot"], g["synthetic"])
    summary["status"] = "panels loaded"
    write_json(run_dir / "summary.json", summary)
    grid = g["grid"]
    ctx = {
        "grid": grid,
        "panels": panels,
        "limits": {"min_cash": g["limits"]["min_cash"], "max_coin": g["limits"]["max_coin"]},
        "costs": g["costs"],
        "snapshot_id": g["snapshot"]["snapshot_id"],
        "commit": g["git"]["commit"],
    }
    progress = summary["grid"] = {
        "blocks": len(tasks(grid)),
        "blocks_logged": 0,
        "runs_logged": 0,
        "folder": "blocks/",
        "note": INTERPRETATIONS["logging"],
    }

    def logged(block: dict) -> None:  # stop rule 6: what a block computed stays in the run folder
        if "stop" in block:
            return
        write_block(run_dir / "blocks", block)
        progress["blocks_logged"] += 1
        progress["runs_logged"] += len(block["runs"])
        write_json(run_dir / "summary.json", summary)

    t = time.time()
    blocks = run_blocks(ctx, args.workers, on_result=logged)
    runtime = time.time() - t
    for block in blocks:
        if "stop" in block:
            rule, message = block["stop"]
            raise Stop(rule, f"{message} (block {block['task']})")
    runs = sort_rows(pd.concat([b["runs"] for b in blocks], ignore_index=True), RUN_SORT)
    lob = sort_rows(pd.concat([b["lob"] for b in blocks], ignore_index=True), LOB_SORT)
    parity = pd.concat([b["parity"] for b in blocks], ignore_index=True)
    failures = pd.concat([b["failures"] for b in blocks], ignore_index=True)
    for name, table in (("runs", runs), ("limit_only_bands", lob), ("parity", parity), ("failures", failures)):
        write_parquet(table, run_dir / f"{name}.parquet")  # before any check or decision (stop rule 6)
    counts = check_counts(runs, lob, parity, grid)
    if runs["run_id"].duplicated().any():
        raise Stop("8", "two runs share a run id")
    runs = add_comparisons(runs, lob)
    write_parquet(runs, run_dir / "runs.parquet")  # with the comparison columns
    csv = runs_csv(runs, lob)
    if len(csv) != counts["expected"]["csv"]:
        raise Stop("8", f"runs.csv has {len(csv)} rows, expected {counts['expected']['csv']} (section 12)")
    failed = int((runs["status"].to_numpy() != H.OK).sum())
    decided = None
    falls = pd.DataFrame(columns=list(H.FALLS_COLUMNS))
    headline = None
    if grid.decidable:
        decided = decisions(runs, lob, grid, returns)
        headline = decided["robust"]["headline"]
        if headline["band"] != H.MISSING and headline["cap"] != H.MISSING:
            falls = H.falls_tables(runs, headline)
    decision = {
        "label": LABEL,
        "status": STATUS,
        "study": STUDY,
        "run": g["k"],
        "data": g["data"],
        "grid": grid.name,
        "decidable": grid.decidable,
        "reason": None
        if grid.decidable
        else "the grid lacks the 6 bands, 7 caps, 3 wallet sizes or both cost levels the rules need (--fast)",
        "thresholds": thresholds(),
        "counts": counts,
        "failed_runs": failed,
        "falls": {"headline": headline, "rows": len(falls), "note": H.FALLS_NOTE}
        if len(falls)
        else {"headline": headline, "rows": 0, "status": "not computed: no headline (MISSING or no decision)"},
        **(decided or {}),
        "rule_E": rule_e(runs, lob, returns) if failed and grid.decidable else None,
    }
    return {
        "runs": runs,
        "lob": lob,
        "parity": parity,
        "failures": failures,
        "csv": csv,
        "falls": falls,
        "decision": decision,
        "summary": {
            "counts": counts["got"],
            "expected": counts["expected"],
            "checks": {
                "path_checks": int((runs["status"].to_numpy() == H.OK).sum() + (lob["status"].to_numpy() == H.OK).sum()),
                "fee_checks": int((runs["status"].to_numpy() == H.OK).sum()),
                "hash_configurations": int(runs.groupby(["source", "scope", "window", "comparator", "reading", "s", "f", "b", "cap", "R"], dropna=False).ngroups),
                "parity": len(parity),
            },
            "failed_runs": failed,
            "grid_runtime_s": runtime,
            "decision_tables": "decision.json (this folder; byte-identical to the tracked copy)",
            "headline": None if not grid.decidable else decision["robust"]["headline"],
            "label_rule_D": None if not grid.decidable else decision["robust"]["label"],
        },
    }


def check_counts(runs: pd.DataFrame, lob: pd.DataFrame, parity: pd.DataFrame, grid: Grid) -> dict:
    """Every run logged (hard rule 8): the counts of section 11 for the grid in use, or stop."""
    exp = expected_counts(grid)["total"]
    comp, reading, scope = runs["comparator"].to_numpy(), runs["reading"].to_numpy(), runs["scope"].to_numpy()
    got = {
        "grid_rolling": int(((comp == "grid") & (reading == "lab") & (scope == "rolling")).sum()),
        "grid_full": int(((comp == "grid") & (scope == "full")).sum()),
        "limit_only": int((comp == "limit-only").sum()),
        "other": int((reading == "other").sum()),
        "runs": len(runs),
        "lob": len(lob),
        "parity_band": int((parity["kind"].to_numpy() == "band").sum()),
        "parity_limit": int((parity["kind"].to_numpy() == "limit-only").sum()),
        "parity": len(parity),
    }
    wrong = {key: (got[key], exp[key]) for key in got if got[key] != exp[key]}
    if wrong:
        raise Stop("8", f"counts differ from the grid's (got, expected): {wrong} (hard rule 8)")
    return {"got": got, "expected": exp}


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write through a temporary file, so a crash never leaves half a table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


BLOCK_TABLES = ("runs", "lob", "parity", "failures")


def block_name(task: tuple) -> str:
    """``KRAKEN-rolling-07``, ``BINANCE-full``: a block's file prefix in ``run<k>/blocks/``."""
    source, scope, k = task
    return f"{source}-{scope}" if scope == "full" else f"{source}-{scope}-{k:02d}"


def write_block(folder: Path, block: dict) -> None:
    """A returned block's four tables, ``<block_name>.<table>.parquet`` (INTERPRETATIONS["logging"])."""
    for table in BLOCK_TABLES:
        write_parquet(block[table], Path(folder) / f"{block_name(block['task'])}.{table}.parquet")


def write_outputs(results: dict, g: dict, run_dir: Path) -> None:
    """decision.json and the tracked files (the four tables are already in ``run_dir``)."""
    decision = json_text(results["decision"])
    write_text(run_dir / "decision.json", decision)
    tracked = tracked_dir(g["out"], g["synthetic"])
    write_text(tracked / "decision.json", decision)
    write_text(tracked / "runs.csv", csv_text(results["csv"]))
    write_text(tracked / "falls.csv", csv_text(results["falls"]))


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return timing_only(args) if args.time else run(args)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
