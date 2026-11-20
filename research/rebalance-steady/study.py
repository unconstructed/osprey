"""rebalance-steady: what run_train.py, freeze.py and run_validate.py share (PLAN.md sections 7-13).

SCOUTING ONLY. Every profit number comes from the reference rebalancer (``lab.runner.portfolio`` through the
adapter ``lab.runner.steady``), not NautilusTrader (AGENTS.md hard rule 3), with the PLACEHOLDER costs of
``config/costs.yaml``. Nothing from this study goes into ``reports/<strategy>/`` or ``strategies/``.

The computations live in tested code (``lab/runner/steady.py``, ``lab/runner/portfolio.py``, ``lab/search``,
``lab/validation``); this file holds the pinned values, the integrity checks (config hash, git state, snapshot,
hash comparison, RUNLOG), the panel loading and the verdict rules. ``research/`` is never imported by ``lab/``.

The test window is never read: every panel comes from ``lab.data.panel.load_panel`` with ``last_close`` at most
2024-07-01 00:00 UTC (its guard raises ``HoldoutWindowError`` for anything later), and :func:`load_study_panel`
checks the returned index again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import subprocess
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.external import HoldoutWindowError, holdout_cut
from lab.data.panel import load_panel
from lab.data.synthetic import synthetic_market
from lab.runner import steady as sd
from lab.runner.portfolio import LIMIT_TOL
from lab.search.report import gates
from lab.search.study import SearchConfig
from lab.validation import montecarlo as mc
from lab.validation import stats

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
STUDY = "rebalance-steady"
LABEL = (
    "SCOUTING: reference rebalancer (lab.runner.portfolio), not NautilusTrader (AGENTS.md hard rule 3); "
    "PLACEHOLDER costs (config/costs.yaml)"
)
DEFAULT_OUT = REPO / "results" / STUDY
DEFAULT_CATALOG = REPO / "data" / "catalog"

SOURCE, ROBUSTNESS, INTERVAL = "KRAKEN", "BINANCE", "1d"
TRAIN_LAST_CLOSE = pd.Timestamp("2023-01-01", tz="UTC")  # PLAN.md section 3: the last train close
VALIDATE_LAST_CLOSE = pd.Timestamp("2024-07-01", tz="UTC")  # the last validate close; nothing later is read
BARS_SHA256 = "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"  # section 3 (stop rule 2)
ROWS = {"train": {SOURCE: 2190, ROBUSTNESS: 1963}, "validate": {SOURCE: 2737, ROBUSTNESS: 2510}}
TRAIN_SIZE, TEST_SIZE = 730, 365  # walk_forward(2190, 730, 365, expanding=True)
VALIDATE_TEST = (2190, 2736)  # Kraken rows of the validate block (section 11)
VALIDATE_KEPT = 546  # kept validate returns, closes 2023-01-03 .. 2024-07-01
SEEDS = {"A": 0, "B": 1}
FOLD_SEED_STEP, FINAL_SEED_OFFSET = 1000, 4000
STABLE_K = 10
MAX_AMENDMENTS = 2
STRICT_EXTRA = 21  # 16 plateau variants, 2 runs at 2x, 1 Binance run, 2 neighbouring mixes (section 12)
FRAGILE_SHARPE = 0.25
DEGRADE_BPS = 10.0
TRADES_PER_PARAM_FLAG = 30
S_BINS = (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.77)  # the s-profile bins; the last one is closed
RISK_FILE = "config/risk_levels.yaml"
CONFIG_FILES = ("config/costs.yaml", "config/splits.yaml", RISK_FILE)
GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")
PASSING = ("PASS", "PASS (weak)")
STUDY_RE = re.compile(r"^rebalance-steady-s(?P<seed>\d+)(?:_a(?P<run>\d+))?_(?P<part>wf\d{2}|final)$")


@dataclass(frozen=True)
class Settings:
    """Simulation sizes. The plan's values are pinned; ``FAST`` is for synthetic dry runs only."""

    n_trials: int = 200
    b3_draws: int = sd.B3_DRAWS
    bootstrap_resamples: int = sd.BOOTSTRAP_RESAMPLES
    mc_sims: int = 1000
    shuffle_sims: int = 5000
    degrade_sims: int = 1000
    profile_mc_sims: int = 1000


PLAN_SETTINGS = Settings()
FAST = Settings(
    n_trials=10,
    b3_draws=30,
    bootstrap_resamples=100,
    mc_sims=60,
    shuffle_sims=60,
    degrade_sims=60,
    profile_mc_sims=20,
)

SECTION_4_READINGS = (
    "The targets satisfy the limits with headroom h: cash >= min_cash + h, each coin <= max_coin - h.",
    "A drifted breach at any daily close forces a full rebalance to target at the next open.",
    "max_coin_pct applies to each coin, not to all coins together.",
    "max_coin_pct does not apply to USDC.",
    "Breaches are judged at daily closes only.",
    "A breach restores every leg to target, not just to the limit.",
)

# Readings the scripts make where the plan is loosely worded. They are part of the config hash.
INTERPRETATIONS = {
    "dirty": "A git tree is dirty when `git status --porcelain --untracked-files=all` prints anything: modified, "
    "staged, deleted or untracked files count; git-ignored files (results/, data/, caches) do not. Real runs of "
    "run_train.py and run_validate.py refuse a dirty tree; a synthetic dry run refuses it too unless "
    "--allow-dirty is given.",
    "writers": "run_train.py writes research/rebalance-steady/trials.csv (every trial of every study of runs "
    "0..k) and evaluations.csv (every evaluation of runs 0..k), rewriting both at the end of each real run; "
    "run_validate.py writes validate.csv. Synthetic dry runs write them to <out>/tracked/ instead, never into "
    "the repo.",
    "commit_between_runs": "run_train.py appends to the tracked RUNLOG.jsonl and rewrites trials.csv and "
    "evaluations.csv, so the lead commits them before an amendment run or the look (the dirty-tree refusal "
    "enforces it).",
    "amendment_row": "run_train.py --amendment k (real data) refuses unless PLAN.md section 13, from the line "
    "starting '**Amendments.**' to the line starting '**Deviations.**', holds a line starting with '- **Amendment "
    "run k' (the dated amendment row of stop rule 7).",
    "paths": "Real runs use the pinned folders only: --out-dir must be results/rebalance-steady, --config-dir unset "
    "(or config/) and --catalog-dir data/catalog, so every run reads config/costs.yaml, splits.yaml and "
    "risk_levels.yaml (sections 4 and 12) and the look's marker is results/rebalance-steady/validate/STARTED "
    "(section 11). Synthetic dry runs refuse results/rebalance-steady and any folder inside the repo (section 12).",
    "same_kind_of_run": "run_train.py --amendment k refuses unless every earlier run k' < k has the same data "
    "(real or synthetic) and the same --fast setting in its start record.",
    "runlog_guard": "run_train.py refuses a run number that the RUNLOG already holds for the same data, and "
    "run_validate.py refuses when the RUNLOG holds a look for the same data (stop rule 9): a deleted results "
    "folder does not reopen a run or the look. Real runs read the tracked research/rebalance-steady/RUNLOG.jsonl, "
    "dry runs <out>/RUNLOG.jsonl.",
    "g6_budget": "G6 uses run 0's train-start reading of config/risk_levels.yaml for the whole study, amendment "
    "runs included; an amendment run records its own reading too but never uses it for G6.",
    "seed_b": "Seed B is evaluated exactly like seed A apart from its chosen parameters: its own k_i, targets and "
    "book for B3 (seeds 10*j + i) and B4, the same paired bootstrap (rng seed 0), its own 2x run and plateau.",
    "reported_run": "The run whose results are reported (frozen and looked at) is the highest-numbered run; "
    "freeze.py refuses unless its summary.json has status 'complete' (a crashed or stopped run is rerun as an "
    "amendment run, stop rules 5-7, so an earlier complete run is superseded, never reported).",
    "triage_before_freeze": "freeze.py refuses a reported run with failed trials (stop rule 4) unless it is given "
    "--triaged '<note>' (the triage's outcome: no code bug, the run stands); FROZEN.json records the note.",
    "look_due": "freeze.py and run_validate.py refuse unless the reported run's train verdict says E1-E5 hold "
    "(section 11; stop rule 8). Synthetic dry runs may pass --any-verdict to exercise the look.",
    "fragility": "E1, E2, E3 and G1-G8 are compared between seeds as pass/fail outcomes: PASS and PASS (weak) "
    "pass, FAIL and MISSING fail.",
    "missing": "A gate whose number (any of its numbers) is NaN is MISSING (it fails).",
    "b3_stitched": "B3 draw j is the 4 fold pieces with seeds 10*j + i stitched in fold order (np.hstack); its "
    "Sharpe is E1's draw Sharpe and its metrics give B3's 5/50/95 percentiles.",
    "b4_span_book": "B4-span starts from S's book V of fold 0 (its only buy fills at the open of fold 0's t0).",
    "costs_paid": "Costs paid over kept rows: the sum of the per-bar cost fractions, and in USD the sum of the "
    "fill legs' costs whose fill row is a kept row.",
    "legs_per_year": "theta_final IN-SAMPLE legs per year = legs / ((rows - 1) / 365); the first buy counts.",
    "breach": "A close is in breach when w_BTC + w_ETH > 1 - min_cash + 1e-9 or a coin > max_coin + 1e-9.",
    "s_profile": "COMPLETE trials of this run's studies, binned by coin_share at edges 0.20, 0.30, ..., 0.70, 0.77 "
    "(each bin [lo, hi), the last one closed).",
    "phase": "Phase sensitivity runs j = 0 .. every - 1 for each fold of both seeds (j = 0 repeats S).",
    "unpaid_turnover": "Per boundary i -> i + 1: |w_btc(i + 1) - w_BTC of S at fold i's last kept close| + the "
    "same for ETH; the 3 boundaries summed.",
    "trades_per_parameter": "S's kept fill rows over the 4 folds / 4 free parameters; flagged below 30.",
    "evaluations": "evaluations.parquet holds one row per fold piece and one stitched row per comparator series; "
    "B3 is recorded per stitched draw (with each fold's fill count), not per fold piece.",
    "look_failure": "A failed consistency check at the look writes look.json with verdict INCONCLUSIVE and exits "
    "non-zero: the look is spent.",
    "risk_exception": "Stop rule 10's exception compares the coin list as read (same order), min_cash and max_coin "
    "with the train-start reading, and needs the config hash to match once the train-start hash of "
    "risk_levels.yaml is put back.",
    "look_hash_check": "run_validate.py also refuses if any file under train/ no longer has the SHA-256 FROZEN.json "
    "holds, or (real data) if research/rebalance-steady/FROZEN.json is not byte-identical to the results copy, or "
    "if FROZEN.json's summary_sha256, theta_final, fold params, E, train verdict, gates and train Sharpes are not "
    "those of the reported run's summary.json.",
    "train_verdict": "After the train phase: NO EDGE (E1 or E2 fails), INCONCLUSIVE (E1 and E2 hold, E3, E4 or E5 "
    "fails) or LOOK DUE (E1-E5 hold; E6 at the look decides EDGE or INCONCLUSIVE).",
    "failed_trials": "Failed trials are counted and listed; the run's numbers stand only after triage (stop rule "
    "4), which the summary flags.",
}

PINNED = {
    "study": STUDY,
    "section_4_readings": list(SECTION_4_READINGS),
    "headroom": sd.HEADROOM,
    "specs": [asdict(p) for p in sd.SPECS],
    "search_config": {
        "n_trials": PLAN_SETTINGS.n_trials,
        "n_workers": 1,
        "n_blocks": 4,
        "penalty": 0.5,
        "periods_per_year": 365,
        "min_trades": 5,
    },
    "seeds": SEEDS,
    "fold_seed": "seed + 1000 * i",
    "final_seed": "seed + 4000",
    "folds": {
        "n": ROWS["train"][SOURCE],
        "train_size": TRAIN_SIZE,
        "test_size": TEST_SIZE,
        "expanding": True,
        "purge": 0,
    },
    "warmup": sd.WARMUP,
    "stable_region_k": STABLE_K,
    "data": {
        "source": SOURCE,
        "robustness": ROBUSTNESS,
        "interval": INTERVAL,
        "train_last_close": TRAIN_LAST_CLOSE.isoformat(),
        "validate_last_close": VALIDATE_LAST_CLOSE.isoformat(),
        "bars_content_sha256": BARS_SHA256,
        "rows": ROWS,
    },
    "settings": asdict(PLAN_SETTINGS),
    "comparators": {
        "b3_seed": "10 * j + i",
        "b2": {"weight": 0.5, "every": 30},
        "b5": {"band": 1.0, "every": 1},
    },
    "criteria": {
        "mean_block": sd.MEAN_BLOCK,
        "bootstrap_seed": 0,
        "fragile_sharpe": FRAGILE_SHARPE,
        "regime_threshold": sd.REGIME_THRESHOLD,
        "plateau": [*sd.PLATEAU_FACTORS, sd.PLATEAU_KEEP],
        "degrade_bps": DEGRADE_BPS,
        "trades_per_param_flag": TRADES_PER_PARAM_FLAG,
    },
    "strict_extra": STRICT_EXTRA,
    "max_amendments": MAX_AMENDMENTS,
    "s_bins": list(S_BINS),
    "interpretations": INTERPRETATIONS,
}


class Refusal(Exception):
    """A start guard refused: nothing was run (exit code 2)."""


class Stop(Exception):
    """A stop rule fired after the start (exit code 3)."""


# ------------------------------------------------------------------------------------------- hashing


def frozen_paths() -> list[str]:
    """The repo-relative files of the config hash (PLAN.md section 12), sorted."""
    fixed = [
        "research/rebalance-steady/PLAN.md",
        "research/rebalance-steady/DATA.md",
        "research/rebalance-steady/study.py",
        "research/rebalance-steady/run_train.py",
        "research/rebalance-steady/freeze.py",
        "research/rebalance-steady/run_validate.py",
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
    globbed = [
        p.relative_to(REPO).as_posix()
        for d in ("lab/search", "lab/validation")
        for p in (REPO / d).glob("*.py")
    ]
    return sorted(set(fixed) | set(globbed))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hashes(config_dir: Path | None = None) -> dict[str, str]:
    """SHA-256 of every frozen file. The three ``config/*.yaml`` files are read from ``config_dir`` (the files
    the run uses; default ``config/``) under their ``config/`` names."""
    cfg = Path(config_dir) if config_dir is not None else CONFIG_DIR
    out = {}
    for rel in frozen_paths():
        path = cfg / Path(rel).name if rel in CONFIG_FILES else REPO / rel
        out[rel] = sha256_file(path)
    return out


def config_hash(hashes: Mapping[str, str]) -> str:
    """SHA-256 over the per-file hashes (sorted by path) and the pinned values."""
    blob = json.dumps({"files": dict(hashes), "pinned": PINNED}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    """SHA-256 of every file under ``root`` (recursively), keyed by the path relative to ``root``."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def compare_hashes(
    recorded_files: Mapping[str, str],
    recorded_config: str,
    current_files: Mapping[str, str],
    start_limits: Mapping,
    config_dir: Path | None = None,
) -> dict:
    """Stop rule 10. ``ok`` when every file hash and the config hash equal the record; also ``ok`` (with an
    ``exception`` record) when the only differing file is ``config/risk_levels.yaml``, the config hash matches
    once its recorded hash is put back, and ``risk_limits("steady")`` still gives the coins, ``min_cash`` and
    ``max_coin`` of ``start_limits``. Otherwise not ``ok``; ``differs`` lists the files."""
    keys = set(recorded_files) | set(current_files)
    differs = sorted(k for k in keys if recorded_files.get(k) != current_files.get(k))
    out = {"ok": False, "differs": differs, "exception": None}
    if not differs:
        out["ok"] = config_hash(current_files) == recorded_config
        if not out["ok"]:
            out["differs"] = ["<pinned values>"]
        return out
    if differs != [RISK_FILE]:
        return out
    restored = dict(current_files)
    restored[RISK_FILE] = recorded_files[RISK_FILE]
    if config_hash(restored) != recorded_config:
        return out
    try:
        now = sd.steady_limits(config_dir)
    except (ValueError, OSError) as exc:
        out["reason"] = f"risk_limits('steady') no longer reads: {exc}"
        return out
    same = (
        list(now["coins"]) == list(start_limits["coins"])
        and now["min_cash"] == start_limits["min_cash"]
        and now["max_coin"] == start_limits["max_coin"]
    )
    if not same:
        out["reason"] = "risk_limits('steady') changed its coins, min_cash or max_coin"
        return out
    out["ok"] = True
    out["exception"] = {
        "rule": "stop rule 10: only config/risk_levels.yaml differs and the Steady coins and limits are unchanged",
        "risk_levels_sha256_recorded": recorded_files[RISK_FILE],
        "risk_levels_sha256_now": current_files[RISK_FILE],
        "limits_now": jsonable(now),
        "g6": "keeps its train-start value; never rescored",
        "deviation": "write a Deviations row in RESULTS.md",
    }
    return out


# ------------------------------------------------------------------------------------- git, logs, json


def git_state(repo: Path = REPO) -> dict:
    """``commit`` (full SHA of HEAD), ``dirty`` (INTERPRETATIONS["dirty"]) and the porcelain lines."""

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
    """Plain JSON types: numpy scalars and arrays, timestamps, tuples; NaN and inf become None."""
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
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def write_json(path: Path, obj) -> None:
    """Write ``obj`` as JSON through a temporary file, so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(jsonable(obj), indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def append_runlog(path: Path, entry: Mapping) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(jsonable(entry), sort_keys=True) + "\n")


def runlog_path(out: Path, synthetic: bool) -> Path:
    """The tracked ``RUNLOG.jsonl`` for real runs; ``<out>/RUNLOG.jsonl`` for synthetic dry runs."""
    return Path(out) / "RUNLOG.jsonl" if synthetic else HERE / "RUNLOG.jsonl"


def tracked_dir(out: Path, synthetic: bool) -> Path:
    """Where the committed copies go: this folder for real runs, ``<out>/tracked`` for dry runs."""
    return Path(out) / "tracked" if synthetic else HERE


def amendment_row_present(plan_text: str, k: int) -> bool:
    """PLAN.md's amendments list (from the line starting ``**Amendments.**`` to the line starting
    ``**Deviations.**``, section 13) holds a line starting with ``- **Amendment run k``
    (INTERPRETATIONS["amendment_row"])."""
    start = re.search(r"^\*\*Amendments\.\*\*", plan_text, re.MULTILINE)
    end = re.search(r"^\*\*Deviations\.\*\*", plan_text, re.MULTILINE)
    if start is None or end is None or end.start() < start.start():
        return False
    pattern = re.compile(rf"^- \*\*Amendment run {k}\b", re.MULTILINE)
    return bool(pattern.search(plan_text[start.start() : end.start()]))


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def check_out_dir(out: Path, synthetic: bool) -> None:
    """A synthetic dry run never writes into the study's results folder or anywhere in the repo (section 12)."""
    if not synthetic:
        return
    where = Path(out).resolve()
    if where == DEFAULT_OUT.resolve() or _inside(where, REPO.resolve()):
        raise Refusal(
            f"--out-dir {out}: a synthetic dry run never writes into {DEFAULT_OUT} or inside the repo "
            "(PLAN.md section 12); use a scratch folder"
        )


def check_real_paths(out: Path, config_dir: Path | None, catalog_dir: Path | None = None) -> None:
    """Real runs use the pinned folders only (INTERPRETATIONS["paths"]): ``out`` is ``DEFAULT_OUT``,
    ``config_dir`` is unset or ``<repo>/config``, and ``catalog_dir`` (when the script reads bars) is
    ``DEFAULT_CATALOG``."""
    if Path(out).resolve() != DEFAULT_OUT.resolve():
        raise Refusal(f"--out-dir {out}: a real run writes only to {DEFAULT_OUT} (PLAN.md sections 11-12)")
    if config_dir is not None and Path(config_dir).resolve() != (REPO / "config").resolve():
        raise Refusal(
            f"--config-dir {config_dir}: a real run reads config/costs.yaml, splits.yaml and risk_levels.yaml "
            "only (PLAN.md sections 4 and 12)"
        )
    if catalog_dir is not None and Path(catalog_dir).resolve() != DEFAULT_CATALOG.resolve():
        raise Refusal(
            f"--catalog-dir {catalog_dir}: a real run reads only {DEFAULT_CATALOG} (PLAN.md section 3)"
        )


def check_paths(out: Path, config_dir: Path | None, catalog_dir: Path | None, synthetic: bool) -> None:
    """:func:`check_out_dir` for dry runs, :func:`check_real_paths` for real ones."""
    if synthetic:
        check_out_dir(out, synthetic)
    else:
        check_real_paths(out, config_dir, catalog_dir)


def runlog_entries(path: Path) -> list[dict]:
    """The RUNLOG's lines as dicts (none when the file does not exist)."""
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# -------------------------------------------------------------------------------------------- the data


def read_snapshot(catalog_dir: Path, synthetic: bool) -> dict:
    """``snapshot_id`` and ``bars_content_sha256`` from ``SNAPSHOT.json`` (metadata only; no bar is read).
    Refuses (stop rule 2) when the bars hash is not the pinned one. Synthetic dry runs read nothing."""
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
            f"stop rule 2: the catalog's bars hash {snap['bars_content_sha256']!r} is not {BARS_SHA256} (PLAN.md "
            "section 3); the counts no longer hold: amend the plan"
        )
    return snap


SYNTHETIC_FIRST = "2017-01-02"
SYNTHETIC_DAYS = 2738  # closes 2017-01-02 .. 2024-07-01, the Kraken grid of DATA.md
SYNTHETIC_GAP = pd.Timestamp("2018-01-13", tz="UTC")  # Kraken ETH has no bar there (DATA.md)
SYNTHETIC_BINANCE_FIRST = pd.Timestamp("2017-08-18", tz="UTC")
_SYNTHETIC_IDS = {
    "BTC/USD.KRAKEN": (SOURCE, "BTC"),
    "ETH/USD.KRAKEN": (SOURCE, "ETH"),
    "BTCUSDT.BINANCE": (ROBUSTNESS, "BTC"),
    "ETHUSDT.BINANCE": (ROBUSTNESS, "ETH"),
}


def synthetic_bar_loader(seed: int) -> Callable:
    """A stand-in for ``lab.data.catalog.load_bars`` that serves SYNTHETIC daily bars (``synthetic_market``) on the
    plan's date grid, for dry runs and tests only: Kraken from close 2017-01-02 with ETH's 2018-01-13 bar missing,
    Binance from close 2017-08-18 (the Kraken bars times a small per-bar factor). The bars do not depend on the
    requested range, so a longer load starts with a shorter one. Snapshot id ``"synthetic"``."""
    market: dict[str, pd.DataFrame] = {}

    def full() -> dict[str, pd.DataFrame]:
        if not market:
            market.update(synthetic_market(SYNTHETIC_DAYS, seed=seed, start=SYNTHETIC_FIRST))
        return market

    def loader(instrument, interval, start=None, end=None, catalog_dir=None) -> pd.DataFrame:
        if interval != INTERVAL or instrument not in _SYNTHETIC_IDS:
            raise ValueError(f"synthetic loader: no {instrument!r} {interval!r} bars")
        source, asset = _SYNTHETIC_IDS[instrument]
        bars = full()[asset].copy()
        bars.index = pd.DatetimeIndex(bars.index, name="ts").as_unit("us")
        if source == SOURCE and asset == "ETH":
            bars = bars.drop(SYNTHETIC_GAP)
        if source == ROBUSTNESS:
            rng = np.random.default_rng([seed, 7, ("BTC", "ETH").index(asset)])
            factor = np.exp(rng.normal(0.0, 0.001, len(bars)))
            for col in ("open", "high", "low", "close"):
                bars[col] = bars[col].to_numpy() * factor
            bars = bars.loc[SYNTHETIC_BINANCE_FIRST:]
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


def load_study_panel(
    source: str,
    last_close: pd.Timestamp,
    *,
    catalog_dir: Path,
    config_dir: Path | None,
    loader: Callable | None,
) -> pd.DataFrame:
    """``load_panel(source, "1d", last_close=...)`` (its guard refuses the test window), checked again here: no
    close after ``last_close`` or the last validate close."""
    if last_close > VALIDATE_LAST_CLOSE:
        raise HoldoutWindowError(f"last_close {last_close} is after {VALIDATE_LAST_CLOSE} (the test window)")
    panel = load_panel(
        source, INTERVAL, last_close=last_close, catalog_dir=catalog_dir, config_dir=config_dir, loader=loader
    )
    if panel.index.max() > last_close or panel.index.max() > holdout_cut(config_dir):
        raise HoldoutWindowError(f"{source}: a close after {last_close} was loaded")
    return panel


def panel_record(panel: pd.DataFrame) -> dict:
    al = panel.attrs["alignment"]
    return {
        "hash": sd.panel_hash(panel),
        "rows": len(panel),
        "first": panel.index[0].isoformat(),
        "last": panel.index[-1].isoformat(),
        "snapshot_id": panel.attrs["snapshot_id"],
        "instruments": panel.attrs["instruments"],
        "dropped": {a: al["dropped"][a]["closes"] for a in al["dropped"]},
        "missing": al["missing"]["closes"],
    }


def search_config(seed: int, settings: Settings) -> SearchConfig:
    return SearchConfig(
        n_trials=settings.n_trials,
        n_workers=1,
        n_blocks=4,
        penalty=0.5,
        seed=seed,
        periods_per_year=365,
        min_trades=5,
    )


def study_tag(seed: int, run: int) -> str:
    """``rebalance-steady-s<seed>`` (run 0) or ``rebalance-steady-s<seed>_a<run>``; ``walk_forward_optimize``
    appends ``_wf00`` .. ``_wf03``, the final study is ``<tag>_final`` (section 7)."""
    return f"{STUDY}-s{seed}" + (f"_a{run}" if run else "")


def parse_study(name: str) -> dict:
    m = STUDY_RE.match(name)
    if not m:
        return {"seed": None, "run": None, "part": None}
    return {"seed": int(m["seed"]), "run": int(m["run"] or 0), "part": m["part"]}


def study_dirs(train_dir: Path) -> list[str]:
    """Every study under ``train_dir`` (a folder holding a ``study.journal``), sorted by name."""
    train_dir = Path(train_dir)
    if not train_dir.is_dir():
        return []
    return sorted(p.name for p in train_dir.iterdir() if (p / "study.journal").is_file())


def trial_table(train_dir: Path, studies: Sequence[str]) -> pd.DataFrame:
    """Every trial (every state) of ``studies``, read from the journals without writing anything: study, run,
    seed, part, number, state, value, the 4 params, w_btc, w_eth, band, sharpe, n_trades, the block Sharpes,
    ``fail_reason`` (empty here: Optuna 5 stores none; run_train.py fills it from :class:`FailureLog`) and the
    study's context (its ``meta.json`` user attrs) as JSON."""
    import optuna
    from optuna.storages import JournalStorage
    from optuna.storages.journal import JournalFileBackend

    rows = []
    for name in studies:
        path = Path(train_dir) / name / "study.journal"
        study = optuna.load_study(study_name=name, storage=JournalStorage(JournalFileBackend(str(path))))
        tag = parse_study(name)
        context = json.dumps(jsonable(study.user_attrs), sort_keys=True)
        for t in study.trials:
            p = t.params
            s, f, b = p.get("coin_share", np.nan), p.get("btc_share", np.nan), p.get("band_rel", np.nan)
            blocks = t.user_attrs.get("block_sharpes") or []
            rows.append(
                {
                    "study": name,
                    "run": tag["run"],
                    "seed": tag["seed"],
                    "part": tag["part"],
                    "number": t.number,
                    "state": t.state.name,
                    "value": t.value if t.value is not None else np.nan,
                    **{f"params_{k}": p.get(k, np.nan) for k in sd.PARAM_NAMES},
                    "w_btc": s * f,
                    "w_eth": s * (1.0 - f),
                    "band": b * s,
                    "sharpe": t.user_attrs.get("sharpe", np.nan),
                    "n_trades": t.user_attrs.get("n_trades", np.nan),
                    **{f"block_sharpe_{i}": blocks[i] if i < len(blocks) else np.nan for i in range(4)},
                    "fail_reason": t.system_attrs.get("fail_reason", ""),
                    "datetime_start": str(t.datetime_start),
                    "context": context,
                    "label": LABEL,
                }
            )
    return pd.DataFrame(rows)


class FailureLog(logging.Handler):
    """Optuna's "Trial N failed ..." warnings while it is entered (Optuna 5 stores no reason with a failed trial),
    so stop rule 4's triage has the error. Use as ``with FailureLog() as log: ...``; ``log.records``."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "failed with parameters" in message:
            tb = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""
            self.records.append({"utc": utc_now(), "message": message, "traceback": tb[-4000:]})

    def __enter__(self) -> FailureLog:
        logging.getLogger("optuna").addHandler(self)
        return self

    def __exit__(self, *exc) -> None:
        logging.getLogger("optuna").removeHandler(self)


def failure_reason(row: Mapping, records: Sequence[Mapping]) -> str:
    """The logged error of a failed trial: the record that starts with Optuna's "Trial <number> failed with
    parameters: <params>" for this trial's number and params (in the order the search suggests them)."""
    params = {name: row[f"params_{name}"] for name in sd.PARAM_NAMES}
    params["every"] = int(params["every"])
    head = f"Trial {int(row['number'])} failed with parameters: {params}"
    found = [r["message"] for r in records if r["message"].startswith(head)]
    return found[0] if found else ""


# ---------------------------------------------------------------------------------------- the numbers


def sharpe(r) -> float:
    return stats.annualized_sharpe(np.asarray(r, dtype=float), 365)


def series_metrics(r) -> dict:
    x = np.asarray(r, dtype=float)
    return {
        "rows": int(x.size),
        "sharpe": sharpe(x),
        "total_return": float(np.prod(1.0 + x) - 1.0),
        "max_drawdown": mc.max_drawdown(x),
        "worst_day": float(x.min()) if x.size else math.nan,
    }


def result_metrics(res: pd.DataFrame, t0: pd.Timestamp) -> dict:
    """Metrics of a backtest result over its kept rows (closes after ``t0``): return metrics plus fill rows,
    turnover, cost fractions and the USD cost of the fill legs on kept rows."""
    kept = res.loc[t0:].iloc[1:]
    out = series_metrics(kept["ret"])
    out["fills"] = int((kept["turnover"] > 0).sum())
    out["turnover"] = float(kept["turnover"].sum())
    out["cost"] = float(kept["cost"].sum())
    fills = res.attrs.get("fills")
    if isinstance(fills, pd.DataFrame) and "cost" in fills:
        out["cost_usd"] = float(fills.loc[fills["ts"] > t0, "cost"].sum())
    return out


def stitched_metrics(r, fold_metrics: Sequence[Mapping]) -> dict:
    """Return metrics of the stitched series plus the folds' fills, turnover and costs, summed over kept rows."""
    out = series_metrics(r)
    for key in ("fills", "turnover", "cost", "cost_usd"):
        values = [m[key] for m in fold_metrics if key in m]
        if values:
            out[key] = int(sum(values)) if key == "fills" else math.fsum(values)
    return out


def e6_parts(sharpe_v: float, sharpe_train: float, sharpe_b4: float, b3_median: float) -> dict:
    """E6 (section 10), reject-only: theta_final(A)'s validate Sharpe > 0, >= 0.5 x the train S Sharpe, > B4's
    validate Sharpe and > the median of B3's validate Sharpes. NaN anywhere fails."""
    parts = {
        "sharpe_positive": bool(sharpe_v > 0),
        "half_train_sharpe": bool(sharpe_v >= 0.5 * sharpe_train),
        "beats_b4": bool(sharpe_v > sharpe_b4),
        "beats_b3_median": bool(sharpe_v > b3_median),
    }
    return {"holds": all(parts.values()), **parts}


def drawdowns(matrix: np.ndarray) -> np.ndarray:
    """Max drawdown of each row of a (draws x rows) return matrix, as ``montecarlo.max_drawdown``."""
    return np.array([mc.max_drawdown(row) for row in np.asarray(matrix, dtype=float)])


def b3_summary(b3: np.ndarray, rank: dict) -> dict:
    """B3's 5/50/95 percentiles of Sharpe, total return and max drawdown over the stitched draws, and S's rank."""
    totals = np.prod(1.0 + b3, axis=1) - 1.0
    return {
        "sharpe": {k: rank[k] for k in ("p5", "p50", "p95")},
        "total_return": mc.percentiles(totals),
        "max_drawdown": mc.percentiles(drawdowns(b3)),
        "rank_p": rank["rank_p"],
        "draws": int(b3.shape[0]),
    }


def overshoot(w_btc, w_eth, limits: Mapping) -> dict:
    """Lowest cash and highest single-coin weight at any close, and the closes in breach of the limits."""
    wb, we = np.asarray(w_btc, dtype=float), np.asarray(w_eth, dtype=float)
    breach = (
        (wb + we > 1.0 - limits["min_cash"] + LIMIT_TOL)
        | (wb > limits["max_coin"] + LIMIT_TOL)
        | (we > limits["max_coin"] + LIMIT_TOL)
    )
    return {
        "lowest_cash": float(np.min(1.0 - wb - we)),
        "highest_coin": float(np.max(np.maximum(wb, we))),
        "closes_in_breach": int(breach.sum()),
    }


def unit_distance(p: Mapping, q: Mapping) -> float:
    """Euclidean distance of two parameter sets in the search box's unit space (as ``stable_region``)."""
    return float(math.sqrt(sum((s.to_unit(p[s.name]) - s.to_unit(q[s.name])) ** 2 for s in sd.SPECS)))


def s_bin(s: float) -> str:
    i = int(np.searchsorted(np.asarray(S_BINS[1:-1]), s, side="right"))
    lo, hi = S_BINS[i], S_BINS[i + 1]
    return f"[{lo:.2f}, {hi:.2f}]" if i == len(S_BINS) - 2 else f"[{lo:.2f}, {hi:.2f})"


def plain_params(params: Mapping) -> dict:
    """The 4 steady params as plain Python numbers (``every`` an int)."""
    out = {k: float(params[k]) for k in sd.PARAM_NAMES if k != "every"}
    every = float(params["every"])
    if every != int(every):
        raise ValueError(f"every must be integral, got {params['every']!r}")
    out["every"] = int(every)
    return {k: out[k] for k in sd.PARAM_NAMES}


# --------------------------------------------------------------------------------- gates and verdicts


def _missing(number) -> bool:
    return number is None or (isinstance(number, float | np.floating) and math.isnan(number))


def gate_status(value: bool, *numbers: float | None) -> str:
    """PASS or FAIL; MISSING when no number is given or any of the gate's numbers is NaN (or None)."""
    if not numbers or any(_missing(x) for x in numbers):
        return "MISSING"
    return "PASS" if bool(value) else "FAIL"


def gate_table(
    sharpes: Mapping[str, float], rep: Mapping, g5: str, regimes_pass: bool, budget: float | None
) -> dict:
    """G1-G9 for one seed (PLAN.md section 9), from its numbers only.

    ``sharpes``: the stitched annualized Sharpes of S at 1x (``"S"``), S at 2x (``"S2"``), B1 and B2. ``rep``: the
    seed's ``overfitting_report`` (G1 its OOS Sharpe, G3 its DSR at the EFFECTIVE count, G4 its mean PBO, G6 its
    Monte Carlo worst-5% drawdown). ``g5``: the plateau verdict. ``regimes_pass``: G8's outcome. ``budget``: G6's
    drawdown budget as a fraction (0.30 for 30%), ``None`` while it is TBD (MISSING). G2: S at 2x > 0.5. G7: S
    above B1 AND above B2. G6: worst-5% drawdown >= -budget (``lab.search.report.gates``)."""
    g = gates(rep)
    if budget is None:
        g6 = "MISSING"
    else:
        key = f"MC worst-5% drawdown within {budget:.0%}"
        g6 = gate_status(gates(rep, budget_drawdown=budget)[key], rep["mc_drawdown_worst5pct"])
    s = sharpes["S"]
    return {
        "G1": gate_status(g["oos_sharpe >= 1.0"], rep["oos_sharpe_annual"]),
        "G2": gate_status(sharpes["S2"] > 0.5, sharpes["S2"]),
        "G3": gate_status(g["dsr (effective) >= 0.95"], rep["dsr_effective_count"]),
        "G4": gate_status(g["pbo <= 0.25"], rep["pbo_mean"]),
        "G5": g5,
        "G6": g6,
        "G7": gate_status(s > sharpes["B1"] and s > sharpes["B2"], s, sharpes["B1"], sharpes["B2"]),
        "G8": "PASS" if regimes_pass else "FAIL",
        "G9": "NOT RUN",
    }


def gate_inputs(sharpes: Mapping[str, float], rep: Mapping, budget: float | None) -> dict:
    """The numbers :func:`gate_table` judged, recorded next to the gates so they can be recomputed."""
    return {
        "G1": rep["oos_sharpe_annual"],
        "G2": sharpes["S2"],
        "G3": rep["dsr_effective_count"],
        "G4": rep["pbo_mean"],
        "G6": {"mc_drawdown_worst5pct": rep["mc_drawdown_worst5pct"], "budget": budget},
        "G7": {"S": sharpes["S"], "B1": sharpes["B1"], "B2": sharpes["B2"]},
    }


def passes(status: str) -> bool:
    return status in PASSING


def fragility(a: Mapping, b: Mapping) -> dict:
    """Section 7: FRAGILE when E1, E2, E3 or any of G1-G8 has a different pass/fail outcome for seeds A and B,
    or their OOS Sharpes differ by more than 0.25. ``a`` and ``b``: ``{"E1": bool, "E2", "E3", "gates":
    {G: status}, "sharpe": float}``."""
    differ = [e for e in ("E1", "E2", "E3") if bool(a[e]) != bool(b[e])]
    differ += [g for g in GATES if passes(a["gates"][g]) != passes(b["gates"][g])]
    gap = abs(a["sharpe"] - b["sharpe"])
    gap_too_big = not (gap <= FRAGILE_SHARPE)  # a NaN gap is fragile
    return {"fragile": bool(differ or gap_too_big), "differ": differ, "sharpe_gap": gap}


def train_verdict(e: Mapping[str, bool]) -> dict:
    """INTERPRETATIONS["train_verdict"] from E1-E5 (seed A)."""
    if not (e["E1"] and e["E2"]):
        return {"verdict": "NO EDGE", "look_due": False}
    if not (e["E3"] and e["E4"] and e["E5"]):
        return {"verdict": "INCONCLUSIVE", "look_due": False}
    return {"verdict": "LOOK DUE", "look_due": True}


def final_verdict(e: Mapping[str, bool | None], stopped: bool = False) -> str:
    """Section 10: NO EDGE if E1 or E2 fails; INCONCLUSIVE if any of E3-E6 fails (a missing E6 fails) or a stop
    rule ended the study; EDGE if E1-E6 all hold."""
    if not (e.get("E1") and e.get("E2")):
        return "NO EDGE"
    if stopped or not all(e.get(k) for k in ("E3", "E4", "E5", "E6")):
        return "INCONCLUSIVE"
    return "EDGE"


def headline(verdict: str, gates: Mapping[str, str]) -> str:
    """Section 10: CANDIDATE FOR AUDIT (EDGE and G1-G8 pass), EDGE, NOT A CANDIDATE (the failing gates
    listed), or the verdict itself."""
    if verdict != "EDGE":
        return verdict
    failing = [f"{g} {gates[g]}" for g in GATES if not passes(gates[g])]
    if not failing:
        return "CANDIDATE FOR AUDIT"
    return "EDGE, NOT A CANDIDATE (" + ", ".join(failing) + ")"
