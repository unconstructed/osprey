"""The protect-gains study script (``research/protect-gains/run.py``) against PLAN.md sections 3-14: the start guards,
the start record and RUNLOG line before any bar, the data stops, every run logged, each consistency stop, the two
stages, and every reported number recomputed from its inputs.

SYNTHETIC data only: every run is a ``--synthetic`` dry run in ``tmp_path`` (``--fast``, or a tiny grid put in its
place), the real catalog loader is replaced by one that fails the test if it is ever reached (except where a test
hands it synthetic bars on purpose), and the git state is injected where a test needs one. Real-data guards run
against stand-ins for every folder a real run uses (``real_folders``), so the repo's recorded runs never decide which
guard a test reaches (TESTING.md #48).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_portfolio import edit_steady_entry

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.panel import load_panel
from lab.runner import holdmix as H
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner.steady import panel_hash

STUDY_DIR = Path(__file__).resolve().parents[1] / "research" / "protect-gains"
NAME = "protect_gains_run"
if NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(NAME, STUDY_DIR / "run.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[NAME] = _module
    _spec.loader.exec_module(_module)
R = sys.modules[NAME]

CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
SEED = 7
LIM = pf.risk_limits("steady")
TINY_TIMING = {"cpu_minutes": 1.0, "wall_minutes_on_2_workers": 0.5, "reps": 1, "seconds_per_busy_run": 0.001}
# The smallest complete dry run, for tests about the guards and the bookkeeping rather than the rules
TINY = R.Grid(
    mixes=((0.5, 0.5),),
    levels={"A": (0.10,), "B": (0.40,)},
    modes=("wait30",),
    readings=("counts",),
    windows={"KRAKEN": (0,), "BINANCE": (48,)},
    name="test-tiny",
)


def _refuse_real_bars(*args, **kwargs):
    raise AssertionError("a test reached the real catalog loader")


@pytest.fixture(autouse=True)
def no_real_bars(monkeypatch):
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)
    monkeypatch.setattr(R, "TIMING_REPS", 1)
    monkeypatch.setattr(R, "TIMING_REPS_FAST", 1)


@pytest.fixture
def tiny(monkeypatch):
    monkeypatch.setattr(R, "FAST", TINY)


@pytest.fixture
def clean_git(monkeypatch):
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(CLEAN))


def dry(out: Path, *extra: str, workers: int = 1, fast: bool = True) -> list[str]:
    return [
        "--synthetic",
        str(SEED),
        *(["--fast"] if fast else []),
        "--out-dir",
        str(out),
        "--workers",
        str(workers),
        *extra,
    ]


def real_folders(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Stand-ins for results/protect-gains, data/catalog and this study's folder (the tracked RUNLOG and copies)."""
    out, cat, here = tmp_path / "results" / "protect-gains", tmp_path / "data" / "catalog", tmp_path / "here"
    monkeypatch.setattr(R, "DEFAULT_OUT", out)
    monkeypatch.setattr(R, "DEFAULT_CATALOG", cat)
    monkeypatch.setattr(R, "HERE", here)
    return out, cat, here


def real_args(out: Path, cat: Path, *extra: str) -> list[str]:
    return ["--out-dir", str(out), "--catalog-dir", str(cat), "--workers", "1", *extra]


def write_snapshot(cat: Path, bars_hash: str = R.BARS_SHA256, snapshot_id: str = "synthetic") -> None:
    cat.mkdir(parents=True, exist_ok=True)
    (cat / catalog.SNAPSHOT_FILE).write_text(
        json.dumps({"snapshot_id": snapshot_id, "bars_content_sha256": bars_hash})
    )


def copy_config(dst: Path) -> Path:
    dst.mkdir(parents=True)
    for name in ("costs.yaml", "splits.yaml", "risk_levels.yaml"):
        shutil.copy(CONFIG_DIR / name, dst / name)
    return dst


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def runlog(path: Path) -> list[dict]:
    return R.runlog_entries(path)


def tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def panels(seed: int = SEED) -> dict[str, pd.DataFrame]:
    loader = R.synthetic_bar_loader(seed)
    return {
        s: load_panel(s, "1d", last_close=R.LAST_CLOSE, catalog_dir="unused", loader=loader)
        for s in H.SOURCES
    }


# ------------------------------------------------------------------------------------- pinned values


def test_the_plan_s_counts_and_grids_are_pinned():
    c = R.expected_counts(R.PLAN_GRID)
    assert (c["stage1"], c["stage2"], c["total"]) == (42_630, 39_420, 82_050)  # section 6
    assert c["stage1"] == (12 * 6 * 2 + 1) * 6 * 49 and c["stage2"] == (12 * 6 + 1) * 6 * (41 + 49)
    assert (
        c["reference"] == 6 * (49 + 41 + 49) == 834
        and c["brake"] == 82_050 - 834
        and c["pool_runs_per_setting"] == 294
    )
    g = R.PLAN_GRID
    assert g.mixes == P.MIXES and g.levels == P.LEVELS and g.modes == P.MODES and g.readings == P.READINGS
    assert g.windows == {"KRAKEN": tuple(range(49)), "BINANCE": tuple(range(8, 49))} and g.decidable
    f = R.FAST
    assert f.decidable and len(f.mixes) == 2 and f.modes == P.MODES
    fast = R.expected_counts(f)
    assert (fast["stage1"], fast["stage2"]) == ((4 * 6 * 2 + 1) * 2 * 3, (4 * 6 + 1) * 2 * (2 + 3))
    assert (
        R.expected_counts(TINY)["stage1"] == 3
        and R.expected_counts(TINY)["stage2"] == 6
        and not TINY.decidable
    )
    assert R.ROWS == {"KRAKEN": 2190, "BINANCE": 1963} and R.LAST_CLOSE == pd.Timestamp(
        "2023-01-01", tz="UTC"
    )
    assert (R.CPU_MINUTES_MAX, R.MAX_AMENDMENTS, R.SNAPSHOT_ID, R.STRESS) == (
        240.0,
        2,
        "1746a21b75683e76",
        2.0,
    )
    assert R.BARS_SHA256 == "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"
    assert R.PANEL_HASHES["KRAKEN"].startswith("355aabe2") and R.PANEL_HASHES["BINANCE"].startswith(
        "2c1a4257"
    )
    assert R.STAGE1_POOL == ("KRAKEN", "1x") and R.STAGE2_POOLS == (("BINANCE", "1x"), ("KRAKEN", "2x"))
    assert R.TIMING_BUSY == ("A", 0.10, "rebound0", "counts") and R.TIMING_ROWS == 731
    assert [R.block_name(t) for t in R.tasks(R.PLAN_GRID, 1)][:2] == ["s1-KRAKEN-1x-00", "s1-KRAKEN-1x-01"]
    assert len(R.tasks(R.PLAN_GRID, 1)) == 49 and len(R.tasks(R.PLAN_GRID, 2)) == 41 + 49


def test_the_hashed_files_and_the_config_hash_move_with_them(tmp_path):
    paths = R.frozen_paths()
    for plan_listed in (
        "research/protect-gains/PLAN.md",
        "research/protect-gains/run.py",
        "lab/runner/protect.py",
        "lab/runner/holdmix.py",
        "lab/runner/portfolio.py",
        "lab/runner/reference.py",
        "config/costs.yaml",
        "config/splits.yaml",
        "config/risk_levels.yaml",
    ):
        assert plan_listed in paths, plan_listed
    assert "lab/runner/trend.py" in paths and paths == sorted(paths)
    assert "lab/validation/montecarlo.py" in paths and "lab/validation/stats.py" in paths  # F's max_drawdown
    hashes = R.file_hashes()
    assert (
        hashes["lab/runner/protect.py"]
        == hashlib.sha256((R.REPO / "lab/runner/protect.py").read_bytes()).hexdigest()
    )
    base = R.config_hash(hashes)
    assert R.config_hash(dict(reversed(list(hashes.items())))) == base
    assert R.config_hash({**hashes, "lab/runner/protect.py": "0" * 64}) != base
    cfg = copy_config(tmp_path / "cfg")
    assert R.file_hashes(cfg) == hashes
    edit_steady_entry(cfg, "min_cash_pct: 20", "min_cash_pct: 21")
    moved = R.file_hashes(cfg)
    assert [k for k in hashes if hashes[k] != moved[k]] == ["config/risk_levels.yaml"]
    pinned = R.pinned_values()
    assert pinned["gains"] == {"0.4": 0.2, "0.5": 0.25, "0.6": 1.0 / 3.0, "0.7": 0.5, "0.8": 1.0}
    assert (
        pinned["tool"] == {"band": 0.3, "cap": 2, "wait": 15, "headroom": 0.02}
        and pinned["deposit"] == 5000.0
    )
    assert pinned["thresholds"]["PROTECT"] == "3 * Q <= 2 * Q0" and pinned["thresholds"]["RESTOP_MAX"] == 0.25
    assert len(pinned["windows"]["KRAKEN"]) == 49 and len(pinned["windows"]["BINANCE"]) == 41


def test_amendment_rows_are_read_from_section_11_s_list_only():
    plan = "x\n**Amendments** (dated):\n- **R1-R4:** ...\n- **Amendment run 1 (2026-12-01): a bug**\n## 12. Allowed\n"
    assert R.amendment_row_present(plan, 1) and not R.amendment_row_present(plan, 2)
    assert not R.amendment_row_present(plan.replace("## 12.", "12."), 1)
    assert not R.amendment_row_present("- **Amendment run 1**\n**Amendments**\n## 12.\n", 1)
    assert not R.amendment_row_present("## 12.\n**Amendments**\n- **Amendment run 1**\n", 1)
    assert not R.amendment_row_present(plan.replace("run 1 ", "run 10 "), 1)
    real = R.PLAN.read_text()
    assert "**Amendments** (dated" in real and "## 12." in real and not R.amendment_row_present(real, 1)


def test_the_out_dir_and_real_path_guards_by_hand(tmp_path, monkeypatch):
    for bad in (R.DEFAULT_OUT, R.DEFAULT_OUT / "x", R.REPO / "scratch", R.REPO):
        with pytest.raises(R.Refusal, match="never writes into"):
            R.check_out_dir(bad)
    R.check_out_dir(tmp_path / "scratch")
    out, cat, _ = real_folders(monkeypatch, tmp_path)
    R.check_real_paths(out, None, cat)
    R.check_real_paths(out, R.REPO / "config", cat)
    with pytest.raises(R.Refusal, match="--out-dir"):
        R.check_real_paths(tmp_path / "elsewhere", None, cat)
    with pytest.raises(R.Refusal, match="--config-dir"):
        R.check_real_paths(out, tmp_path / "cfg", cat)
    with pytest.raises(R.Refusal, match="--catalog-dir"):
        R.check_real_paths(out, None, tmp_path / "cat2")


def test_jsonable_and_run_ids_and_the_sort_order():
    assert R.jsonable(
        {1.5: [np.float64("nan"), np.int64(3), pd.NaT, pd.Timestamp("2020-01-01", tz="UTC")]}
    ) == {"1.5": [None, 3, None, "2020-01-01T00:00:00+00:00"]}
    assert R.jsonable((np.bool_(True), np.array([1.0, math.inf]), np.datetime64("NaT", "us"))) == [
        True,
        [1.0, None],
        None,
    ]
    assert (
        R.run_id(1, "KRAKEN", "1x", 3, 0.7, 0.75, "A", 0.1, "trend", "counts")
        == "1:KRAKEN:1x:3:0.7:0.75:A:0.1:trend:counts"
    )
    assert (
        R.run_id(2, "BINANCE", "1x", 8, 0.5, 0.5, "R", None, "none", "none")
        == "2:BINANCE:1x:8:0.5:0.5:R:-:none:none"
    )
    assert R.run_id(2, "BINANCE", "1x", 8, 0.5, 0.5, "R", math.nan, "none", "none").endswith(":R:-:none:none")
    frame = pd.DataFrame(
        {
            "stage": [1, 1, 1, 1],
            "source": ["KRAKEN"] * 4,
            "cost": ["1x"] * 4,
            "window": [0] * 4,
            "s": [0.5] * 4,
            "f": [0.5] * 4,
            "reading": ["counts", "separate", "counts", "none"],
            "line": ["A", "A", "A", "R"],
            "level": [0.2, 0.1, 0.1, math.nan],
            "mode": ["trend", "wait30", "rebound-5", "none"],
        }
    )
    got = R.sort_rows(frame)
    assert list(zip(got["line"], got["reading"], got["level"].fillna(-1), got["mode"], strict=True)) == [
        ("R", "none", -1, "none"),
        ("A", "separate", 0.1, "wait30"),
        ("A", "counts", 0.1, "rebound-5"),
        ("A", "counts", 0.2, "trend"),
    ]


def test_the_synthetic_panels_have_the_plan_s_shape_and_pass_the_panel_checks():
    got = panels()
    for source in H.SOURCES:
        assert len(got[source]) == R.ROWS[source]
        R.check_panel(source, got[source], synthetic=True)
    assert got["KRAKEN"].index[0] == pd.Timestamp("2017-01-02", tz="UTC")
    assert pd.Timestamp("2018-01-13", tz="UTC") not in got["KRAKEN"].index
    assert got["BINANCE"].index[0] == pd.Timestamp("2017-08-18", tz="UTC")
    with pytest.raises(R.Stop, match="panel hash"):
        R.check_panel("KRAKEN", got["KRAKEN"], synthetic=False)


def test_the_timing_projects_the_plan_s_grid_by_hand():
    t = R.measure_throughput(LIM, None, 1)
    assert (t["reference_runs"], t["brake_runs"]) == (834, 81_216)
    want = (834 * t["seconds_per_reference_run"] + 81_216 * t["seconds_per_busy_run"]) / 60.0
    assert t["cpu_minutes"] == pytest.approx(want, rel=1e-12) and t["limit_cpu_minutes"] == 240.0
    assert t["busy_stops"] >= 1 and t["busy_passes"] == t["busy_stops"] + 1
    assert t["seconds_per_pass"] == t["seconds_per_busy_run"] / t["busy_passes"]


def test_time_mode_writes_its_projection_to_a_scratch_folder_only(tmp_path, capsys):
    out = tmp_path / "timing"
    assert R.main(["--time", "--out-dir", str(out)]) == 0
    assert read_json(out / "timing.json")["timing"]["brake_runs"] == 81_216
    assert "CPU-minutes for the plan's grid" in capsys.readouterr().out
    assert R.main(["--time", "--out-dir", str(R.REPO / "x")]) == 2
    assert R.main(["--time", "--synthetic", "1", "--out-dir", str(out)]) == 2
    assert "runs on its own" in capsys.readouterr().err


# ------------------------------------------------------------------------------------- start guards


def test_bad_flags_are_refused_before_anything_is_written(tmp_path, capsys):
    out = tmp_path / "out"
    assert R.main(["--fast", "--out-dir", str(out)]) == 2
    assert "--fast is for synthetic dry runs only" in capsys.readouterr().err
    assert R.main(dry(out, "--amendment", "0")) == 2
    assert R.main(dry(out, workers=0)) == 2
    assert not out.exists()


def test_a_dry_run_never_writes_into_the_study_folder_or_the_repo(tmp_path, capsys, tiny):
    before = tree(STUDY_DIR)
    results = R.REPO / "results" / "protect-gains"
    existed = results.exists()
    for bad in (results, results / "dry", STUDY_DIR / "dry", R.REPO / "dry-run"):
        assert R.main(dry(bad)) == 2
        assert "never writes into" in capsys.readouterr().err
        assert not bad.exists() or bad == results and existed
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    assert tree(STUDY_DIR) == before and results.exists() == existed
    assert sorted(p.name for p in out.iterdir()) == ["run0", "tracked"]
    assert sorted(p.name for p in (out / "tracked").iterdir()) == [
        "RUNLOG.jsonl",
        "decision.json",
        "runs.csv",
    ]
    assert sorted(p.name for p in (out / "run0").iterdir()) == [
        "blocks",
        "decision.json",
        "failures.parquet",
        "runs.parquet",
        "start.json",
        "stops.parquet",
        "summary.json",
    ]
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"] == "complete" and summary["counts"] == {"stage1": 3, "stage2": 6, "total": 9}
    assert read_json(out / "run0" / "decision.json")["stage1"] is None  # the tiny grid decides nothing


def test_real_runs_use_the_pinned_folders_only(tmp_path, monkeypatch, clean_git, capsys):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat, bars_hash="0" * 64)
    cfg = copy_config(tmp_path / "cfg")
    for args, what in (
        (["--out-dir", str(tmp_path / "other"), "--catalog-dir", str(cat)], "--out-dir"),
        (real_args(out, cat, "--config-dir", str(cfg)), "--config-dir"),
        (["--out-dir", str(out), "--catalog-dir", str(tmp_path / "cat2")], "--catalog-dir"),
    ):
        assert R.main(args) == 2
        assert what in capsys.readouterr().err
    assert not out.exists() and not here.exists()
    assert (
        R.main(real_args(out, cat)) == 2
    )  # the pinned folders pass and reach the next guard (the bars hash)
    assert "bars hash" in capsys.readouterr().err and not out.exists() and not here.exists()


def test_a_dirty_tree_is_refused_on_real_data_before_anything_is_written(tmp_path, monkeypatch, capsys, tiny):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(DIRTY))
    assert R.main(real_args(out, cat)) == 2
    err = capsys.readouterr().err
    assert "the git tree is dirty" in err and "stray.txt" in err
    assert not out.exists() and not here.exists()
    assert R.main(dry(tmp_path / "dry")) == 0  # a dry run on the same dirty tree runs and records the state
    assert read_json(tmp_path / "dry" / "run0" / "start.json")["git"] == DIRTY


def test_a_real_run_0_runs_once(tmp_path, monkeypatch, clean_git, capsys):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat, bars_hash="0" * 64)
    out.mkdir(parents=True)
    assert R.main(real_args(out, cat)) == 2
    assert "run 0 runs once" in capsys.readouterr().err
    out.rmdir()
    R.append_runlog(here / "RUNLOG.jsonl", {"script": "run.py", "run": 0, "data": "real", "utc": "t"})
    assert R.main(real_args(out, cat)) == 2
    assert "already records real run 0" in capsys.readouterr().err
    (here / "RUNLOG.jsonl").write_text(json.dumps({"script": "run.py", "run": 0, "data": "synthetic"}) + "\n")
    assert R.main(real_args(out, cat)) == 2
    assert "bars hash" in capsys.readouterr().err and not out.exists()


def test_the_amendment_rules(tmp_path, monkeypatch, capsys, tiny):
    monkeypatch.setattr(R, "PLAN_GRID", TINY)  # a broken guard below must not start the plan's 82,050 runs
    out = tmp_path / "dry"
    assert R.main(dry(out, "--amendment", "1")) == 2
    assert "run0" in capsys.readouterr().err and not out.exists()
    assert R.main(dry(out)) == 0
    assert R.main(dry(out)) == 2
    assert "run 0 runs once" in capsys.readouterr().err
    for k in ("3", "-1"):
        assert R.main(dry(out, "--amendment", k)) == 2
        assert "numbered 1..2" in capsys.readouterr().err
    assert R.main(dry(out, "--amendment", "2")) == 2
    assert "run1" in capsys.readouterr().err
    assert R.main(dry(out, "--amendment", "1", fast=False)) == 2
    assert "fast True" in capsys.readouterr().err
    (out / "run1").mkdir()
    assert R.main(dry(out, "--amendment", "1")) == 2
    assert "never resumed" in capsys.readouterr().err
    (out / "run1").rmdir()
    R.append_runlog(out / "tracked" / "RUNLOG.jsonl", {"script": "run.py", "run": 1, "data": "synthetic"})
    assert R.main(dry(out, "--amendment", "1")) == 2
    assert "already records synthetic run 1" in capsys.readouterr().err
    lines = (out / "tracked" / "RUNLOG.jsonl").read_text().splitlines()
    (out / "tracked" / "RUNLOG.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    (out / "run0" / "start.json").write_text("{}")
    assert R.main(dry(out, "--amendment", "1")) == 2
    assert "cannot read run 0's start record" in capsys.readouterr().err
    (out / "run0" / "start.json").write_text(json.dumps({"data": "synthetic", "fast": True}))
    assert R.main(dry(out, "--amendment", "1")) == 0
    start = read_json(out / "run1" / "start.json")
    assert start["run"] == 1 and start["fast"] is True
    assert [e["run"] for e in runlog(out / "tracked" / "RUNLOG.jsonl") if "event" not in e] == [0, 1]


def test_a_real_amendment_needs_its_plan_row(tmp_path, monkeypatch, clean_git, capsys):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    (out / "run0").mkdir(parents=True)
    (out / "run0" / "start.json").write_text(json.dumps({"data": "real", "fast": False}))
    write_snapshot(cat, bars_hash="0" * 64)
    assert R.main(real_args(out, cat, "--amendment", "1")) == 2
    assert "lists no '- **Amendment run 1' row" in capsys.readouterr().err
    plan = tmp_path / "PLAN.md"
    plan.write_text("**Amendments** (dated)\n- **Amendment run 1 (2026-12-01): a bug**\n## 12. x\n")
    monkeypatch.setattr(R, "PLAN", plan)
    assert R.main(real_args(out, cat, "--amendment", "1")) == 2
    assert "bars hash" in capsys.readouterr().err  # the next guard


@pytest.mark.parametrize("key", ["min_cash_pct", "max_coin_pct"])
def test_a_steady_level_without_both_limits_is_refused(tmp_path, key, capsys):
    cfg = copy_config(tmp_path / "cfg")
    value = "20" if key == "min_cash_pct" else "60"
    edit_steady_entry(cfg, f"  {key}: {value}\n", "")
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(cfg))) == 2
    assert "must set both min_cash_pct and max_coin_pct" in capsys.readouterr().err
    assert not (tmp_path / "dry").exists()


@pytest.mark.parametrize("value", ["1", "3", "2.5", "true"])
def test_the_tool_s_limit_as_read_must_be_the_plan_s_2(tmp_path, value, capsys):
    cfg = copy_config(tmp_path / "cfg")
    edit_steady_entry(cfg, "hold_mix_max_rebalances_per_30d: 2", f"hold_mix_max_rebalances_per_30d: {value}")
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(cfg))) == 2
    assert "hold_mix_max_rebalances_per_30d is" in capsys.readouterr().err
    edit_steady_entry(cfg, f"hold_mix_max_rebalances_per_30d: {value}", "")
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(cfg))) == 2
    assert "is None, not the plan's 2" in capsys.readouterr().err
    assert not (tmp_path / "dry").exists()
    bad = copy_config(tmp_path / "bad")
    (bad / "risk_levels.yaml").write_text("steady: [1, 2]\n")
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(bad))) == 2
    assert "does not read" in capsys.readouterr().err


def test_limits_that_refuse_a_mix_stop_the_start(tmp_path, capsys):
    cfg = copy_config(tmp_path / "cfg")
    edit_steady_entry(cfg, "max_coin_pct: 60", "max_coin_pct: 54")  # BTC 0.525 + h 0.02 > 0.54
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(cfg))) == 2
    assert "refuse a mix" in capsys.readouterr().err and not (tmp_path / "dry").exists()


def test_the_catalog_snapshot_is_checked_before_any_bar(tmp_path, monkeypatch, clean_git, capsys):
    out, cat, _ = real_folders(monkeypatch, tmp_path)
    assert R.main(real_args(out, cat)) == 2
    assert "cannot read" in capsys.readouterr().err
    write_snapshot(cat, snapshot_id="")
    assert R.main(real_args(out, cat)) == 2
    assert "names no snapshot_id" in capsys.readouterr().err
    assert not out.exists()
    snap = R.read_snapshot(cat.parent / "x", synthetic=True)
    assert snap["plan_snapshot_id"] == "1746a21b75683e76"
    write_snapshot(cat, snapshot_id="other-id")
    assert R.read_snapshot(cat, synthetic=False) == {
        "snapshot_id": "other-id",
        "bars_content_sha256": R.BARS_SHA256,
        "plan_snapshot_id": "1746a21b75683e76",
    }  # the id is recorded; the hashes decide (INTERPRETATIONS["snapshot"])


def test_a_projection_above_240_cpu_minutes_refuses_a_real_run_only(
    tmp_path, monkeypatch, clean_git, capsys, tiny
):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    over = {**TINY_TIMING, "cpu_minutes": 240.000001}
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(over))
    assert R.main(real_args(out, cat)) == 2
    assert "stop rule 7: the projection is 240.0 CPU-minutes" in capsys.readouterr().err
    assert not out.exists() and not here.exists()
    assert R.main(dry(tmp_path / "dry")) == 0  # a dry run records it
    assert read_json(tmp_path / "dry" / "run0" / "start.json")["timing"]["cpu_minutes"] == 240.000001
    exactly = {**TINY_TIMING, "cpu_minutes": 240.0}
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(exactly))
    monkeypatch.setattr(catalog, "load_bars", R.synthetic_bar_loader(SEED))  # on purpose: past the start
    assert R.main(real_args(out, cat)) == 3  # exactly 240 starts (and stops at the synthetic panels' hash)
    assert read_json(out / "run0" / "summary.json")["stop"]["rule"] == "2"


def test_a_timing_that_fails_refuses_the_start(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise RuntimeError("engine broken")

    monkeypatch.setattr(P, "protect", broken)
    assert R.main(dry(tmp_path / "dry")) == 2
    assert "the A1 timing failed: RuntimeError: engine broken" in capsys.readouterr().err


def test_the_start_record_and_the_runlog_line_exist_before_any_bar_is_read(tmp_path, monkeypatch, tiny):
    out = tmp_path / "dry"
    seen = []
    real_loader = R.synthetic_bar_loader

    def watching(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            seen.append(
                ((out / "run0" / "start.json").is_file(), len(runlog(out / "tracked" / "RUNLOG.jsonl")))
            )
            assert end == R.LAST_CLOSE  # the train window only
            return inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)

        return loader

    monkeypatch.setattr(R, "synthetic_bar_loader", watching)
    assert R.main(dry(out)) == 0
    assert seen and all(s == (True, 1) for s in seen) and len(seen) == 4
    start = read_json(out / "run0" / "start.json")
    for key in (
        "utc",
        "git",
        "config_hash",
        "file_hashes",
        "risk_limits",
        "costs",
        "grid",
        "windows",
        "interpretations",
    ):
        assert key in start
    assert (
        start["risk_limits"]["min_cash"] == LIM["min_cash"]
        and start["risk_limits"]["sha256"] == LIM["sha256"]
    )
    assert start["risk_limits"]["hold_mix_max_rebalances_per_30d"] == 2
    assert start["windows"]["KRAKEN"][0] == [0, "2017-01-02T00:00:00+00:00", "2019-01-01T00:00:00+00:00"]
    assert start["costs"]["2x"]["gas_usd_per_trade"] == 2 * start["costs"]["1x"]["gas_usd_per_trade"]
    assert start["costs"]["1x"]["capital_usd"] == 5000.0 and start["costs"]["2x"]["pool_fee_bps"] == 10.0
    assert start["config_hash"] == R.config_hash(R.file_hashes()) and start["snapshot"]["plan_snapshot_id"]
    want = panels()
    for source in H.SOURCES:
        assert start["panels"][source]["rows"] == R.ROWS[source]
        assert start["panels"][source]["hash"] == panel_hash(want[source])
    assert start["year_returns"] == {str(k): v for k, v in H.year_returns(want["KRAKEN"]).items()}
    line = runlog(out / "tracked" / "RUNLOG.jsonl")[0]
    assert {k: line[k] for k in ("script", "run", "data", "snapshot_id", "config_hash")} == {
        "script": "run.py",
        "run": 0,
        "data": "synthetic",
        "snapshot_id": "synthetic",
        "config_hash": start["config_hash"],
    }


# ------------------------------------------------------------------------------------- data stops

ORIGINAL_LOADER = R.synthetic_bar_loader  # the loaders below wrap this one, never an already-patched one


def _leaky(close: str):
    real_loader = ORIGINAL_LOADER

    def factory(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            extra = bars.iloc[[-1]].copy()
            stamp = pd.Timestamp(close)
            extra.index = pd.DatetimeIndex([stamp], name="ts").as_unit("us")
            if stamp.tzinfo is None:
                bars = bars.tz_localize(None)
            out = pd.concat([bars, extra])
            out.attrs = bars.attrs
            return out

        return loader

    return factory


@pytest.mark.parametrize("close", ["2023-01-02T00:00:00+00:00", "2024-07-02T00:00:00+00:00", "2023-01-02"])
def test_a_close_after_the_train_window_stops_the_run_before_any_backtest(tmp_path, monkeypatch, close):
    monkeypatch.setattr(R, "synthetic_bar_loader", _leaky(close))
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "3" and "report the incident" in summary["status"]
    assert "2023-01-02" in summary["status"] or "2024-07-02" in summary["status"]
    events = [e for e in runlog(out / "tracked" / "RUNLOG.jsonl") if "event" in e]
    assert events == [{**events[0], "event": "stop rule 3"}]
    assert "panels" not in read_json(out / "run0" / "start.json")
    assert not (out / "run0" / "runs.parquet").exists() and not (out / "tracked" / "runs.csv").exists()


def _reshaped(change):
    real_loader = ORIGINAL_LOADER

    def factory(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            got = change(instrument, bars)
            got.attrs = bars.attrs
            return got

        return loader

    return factory


def test_a_wrong_row_count_or_a_window_close_missing_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    drop_first = _reshaped(lambda inst, bars: bars.iloc[1:] if "KRAKEN" in inst else bars)
    monkeypatch.setattr(R, "synthetic_bar_loader", drop_first)
    assert R.main(dry(tmp_path / "a")) == 3
    summary = read_json(tmp_path / "a" / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "2189 rows, expected 2190" in summary["status"]
    assert (
        read_json(tmp_path / "a" / "run0" / "start.json")["panels"]["KRAKEN"]["rows"] == 2189
    )  # recorded first
    # a Binance close missing inside window 8 with the extra bar added before it: still 1963 rows
    gone = pd.Timestamp("2017-09-10", tz="UTC")
    extra = pd.Timestamp("2017-08-17", tz="UTC")

    def swap(inst, bars):
        if "BINANCE" not in inst:
            return bars
        row = bars.iloc[[0]].copy()
        row.index = pd.DatetimeIndex([extra], name="ts").as_unit("us")
        return pd.concat([row, bars.drop(gone)])

    monkeypatch.setattr(R, "synthetic_bar_loader", _reshaped(swap))
    assert R.main(dry(tmp_path / "b")) == 3
    summary = read_json(tmp_path / "b" / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "BINANCE window 8" in summary["status"]


def test_real_data_with_other_bars_stops_the_run(tmp_path, monkeypatch, clean_git, tiny):
    out, cat, _ = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(TINY_TIMING))
    monkeypatch.setattr(catalog, "load_bars", R.synthetic_bar_loader(SEED))  # on purpose: other bars
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    assert R.main(real_args(out, cat)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "panel hash" in summary["status"]


def test_load_panel_refusing_the_bars_is_stop_rule_2(tmp_path, monkeypatch):
    def broken(seed):
        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            return ORIGINAL_LOADER(seed)(instrument, "1d", start=start, end=end).iloc[::-1]

        return loader

    monkeypatch.setattr(R, "synthetic_bar_loader", broken)
    assert R.main(dry(tmp_path / "dry")) == 3
    summary = read_json(tmp_path / "dry" / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "load_panel refused" in summary["status"]


# ------------------------------------------------------------------------------------- consistency stops


def _stopped(out: Path, *, stage_tables: bool = False) -> dict:
    """A stop rule 5: recorded, nothing reported, and every block that returned in run0/blocks/."""
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "5", summary["status"]
    assert not (out / "tracked" / "runs.csv").exists() and not (out / "tracked" / "decision.json").exists()
    assert not (out / "run0" / "decision.json").exists()
    assert (out / "run0" / "runs.parquet").exists() is stage_tables
    folder = out / "run0" / "blocks"
    blocks = sorted(folder.glob("*.runs.parquet")) if folder.is_dir() else []
    logged = sum(s.get("blocks_logged", 0) for s in summary.get("grid", {}).values())
    assert len(blocks) == logged
    assert [e.get("event") for e in runlog(out / "tracked" / "RUNLOG.jsonl")] == [None, "stop rule 5"]
    return summary


def _stub_timing(monkeypatch):
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(TINY_TIMING))


def test_a_tool_copy_that_differs_from_hold_mix_stops_the_run(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = H.hold_mix

    def off(params, bars, costs=None):
        res = real(params, bars, costs)
        res.attrs["held"] = np.asarray([*res.attrs["held"], len(bars) - 2], dtype=np.int64)
        return res

    monkeypatch.setattr(H, "hold_mix", off)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "the tool copy's held differs from hold_mix's" in _stopped(out)["status"]


def test_a_tool_copy_whose_outcome_differs_from_hold_mix_s_stops_the_run(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)

    def refuses(params, bars, costs=None):
        raise ValueError("costs of the fill are 100%")

    monkeypatch.setattr(H, "hold_mix", refuses)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "the tool copy's outcome" in _stopped(out)["status"]


def test_both_refusing_alike_is_a_failed_reference_run_and_its_pool_is_missing(tmp_path, monkeypatch, tiny):
    """The engine refusing a fill in R and in its hold_mix check alike is not a consistency stop: R is a failed run
    (stop rule 4), logged with its error; the brake runs of its window get C = NaN."""
    _stub_timing(monkeypatch)
    real_protect, real_hold_mix = P.protect, H.hold_mix
    first = pd.Timestamp("2017-01-02", tz="UTC")

    def refusing(params, bars, costs=None, signal=None):
        if "line" not in params and bars.index[0] == first:
            raise ValueError("a refusal both engines give")
        return real_protect(params, bars, costs, signal)

    def refusing_too(params, bars, costs=None):
        if bars.index[0] == first:
            raise ValueError("a refusal both engines give")
        return real_hold_mix(params, bars, costs)

    monkeypatch.setattr(P, "protect", refusing)
    monkeypatch.setattr(H, "hold_mix", refusing_too)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    window0 = runs[(runs["window"] == 0) & (runs["source"] == "KRAKEN")]
    ref = window0[window0["line"] == "R"]
    assert len(ref) == 2 and (ref["status"] == "failed").all()
    assert (ref["error"] == "ValueError: a refusal both engines give").all()
    brake = window0[window0["line"] != "R"]
    assert brake["C"].isna().all() and (brake["status"] == "ok").all()
    failures = pd.read_parquet(out / "run0" / "failures.parquet")
    assert len(failures) == 2 and "Traceback" in failures["traceback"].iloc[0]
    assert read_json(out / "run0" / "decision.json")["failed_runs"] == 2


@pytest.mark.parametrize("what", ["events", "orders", "book", "fees"])
def test_each_brake_run_check_stops_the_run(tmp_path, monkeypatch, tiny, what):
    _stub_timing(monkeypatch)
    real_orders = P.check_orders

    def raising(*args, **kwargs):
        raise P.ConsistencyError(f"a broken {what} check")

    def raising_on_brake_runs(result, **kwargs):  # R's check (reading None) keeps working
        if kwargs.get("reading") is None:
            return real_orders(result, **kwargs)
        raise P.ConsistencyError("a broken orders check")

    target = {
        "events": "check_events",
        "orders": "check_orders",
        "book": "check_book",
        "fees": "run_measures",
    }[what]
    monkeypatch.setattr(P, target, raising_on_brake_runs if what == "orders" else raising)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert f"a broken {what} check" in _stopped(out)["status"]


def test_a_recompute_that_disagrees_with_the_re_running_stops_the_run(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = P.recompute_events

    def dropped(result, signal, **kw):
        got = real(result, signal, **kw)
        return {**got, "stops": got["stops"][1:]} if got["stops"] else got

    monkeypatch.setattr(P, "recompute_events", dropped)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "differ from the one-pass recompute" in _stopped(out)["status"]


def test_a_lost_run_stops_the_run_at_the_count(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = R._block

    def lossy(stage, source, cost, k):
        got = real(stage, source, cost, k)
        if stage == 2 and source == "BINANCE":
            got["runs"] = got["runs"].iloc[1:]
        return got

    monkeypatch.setattr(R, "_block", lossy)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "stage 2 logged 5 runs, expected 6" in _stopped(out, stage_tables=True)["status"]


def test_two_runs_with_one_run_id_stop_the_run(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = R._block

    def twice(stage, source, cost, k):
        got = real(stage, source, cost, k)
        got["runs"].loc[1, "run_id"] = got["runs"].loc[0, "run_id"]
        return got

    monkeypatch.setattr(R, "_block", twice)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "two runs share a run id" in _stopped(out, stage_tables=True)["status"]


def test_a_hashed_file_that_changes_during_the_run_stops_it(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = R.file_hashes
    calls = []

    def moving(config_dir=None):
        calls.append(1)
        got = real(config_dir)
        return got if len(calls) == 1 else {**got, "lab/runner/protect.py": "0" * 64}

    monkeypatch.setattr(R, "file_hashes", moving)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "a hashed file changed during the run" in _stopped(out, stage_tables=True)["status"]


def test_a_failed_brake_run_is_logged_and_the_grid_goes_on(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = P.protect

    def failing(params, bars, costs=None, signal=None):
        if params.get("line") == "B" and bars.index[0] == pd.Timestamp("2017-01-02", tz="UTC"):
            raise RuntimeError("a synthetic failure")
        return real(params, bars, costs, signal)

    monkeypatch.setattr(P, "protect", failing)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    failed = runs[runs["status"] != "ok"]
    assert sorted(failed["run_id"]) == [
        "1:KRAKEN:1x:0:0.5:0.5:B:0.4:wait30:counts",
        "2:KRAKEN:2x:0:0.5:0.5:B:0.4:wait30:counts",
    ]
    assert (failed["error"] == "RuntimeError: a synthetic failure").all() and failed["F"].isna().all()
    assert (failed["stops"] == -1).all() and len(runs) == 9
    assert read_json(out / "run0" / "summary.json")["failed_runs"] == 2
    csv = pd.read_csv(out / "tracked" / "runs.csv")
    assert len(csv) == 9 and (csv["status"] == "failed").sum() == 2


def test_a_failed_run_makes_the_decisions_it_feeds_missing():
    runs = pd.DataFrame(
        {
            "source": ["KRAKEN"] * 3,
            "cost": ["1x"] * 3,
            "reading": ["none", "counts", "counts"],
            "line": ["R", "A", "A"],
            "level": [math.nan, 0.1, 0.1],
            "mode": ["none", "wait30", "trend"],
            "s": [0.5] * 3,
            "f": [0.5] * 3,
            "window": [0] * 3,
            "status": ["ok", "failed", "ok"],
            "F": [0.3, math.nan, 0.1],
            "C": [0.0, math.nan, 0.0],
            "buybacks": [0, -1, 1],
            "restops": [0, -1, 0],
        }
    )
    d = P.defaults(runs, "counts")
    assert d["D1"]["A"]["wait30"]["default"] == P.MISSING and d["D2"]["A"]["mode"] == P.MISSING
    assert d["D3"]["line"] == P.MISSING


def test_a_stop_in_a_later_block_keeps_the_blocks_that_returned(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = R._block

    def stopping(stage, source, cost, k):
        if stage == 2 and source == "KRAKEN":
            raise R.Stop("5", "a synthetic stop in the last block")
        return real(stage, source, cost, k)

    monkeypatch.setattr(R, "_block", stopping)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = _stopped(out, stage_tables=True)  # stage 1's tables were written before stage 2 began
    assert (
        "a synthetic stop in the last block" in summary["status"]
        and "(2, 'KRAKEN', '2x', 0)" in summary["status"]
    )
    names = sorted(p.name for p in (out / "run0" / "blocks").glob("*.runs.parquet"))
    assert names == ["s1-KRAKEN-1x-00.runs.parquet", "s2-BINANCE-1x-48.runs.parquet"]
    assert summary["grid"]["stage1"] == {"blocks": 1, "blocks_logged": 1, "runs_logged": 3}
    assert summary["grid"]["stage2"] == {"blocks": 2, "blocks_logged": 1, "runs_logged": 3}
    assert len(pd.read_parquet(out / "run0" / "runs.parquet")) == 3


def test_with_workers_a_block_already_running_when_another_stops_is_logged(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    marker = tmp_path / "kraken-2x-done"
    real = R._block

    def blocks(stage, source, cost, k):
        if stage == 2 and source == "BINANCE":
            deadline = time.time() + 120
            while not marker.exists() and time.time() < deadline:
                time.sleep(0.02)
            raise R.Stop("5", "a synthetic stop in the first stage-2 block")
        got = real(stage, source, cost, k)
        if stage == 2:
            marker.write_text("done")
        return got

    monkeypatch.setattr(R, "_block", blocks)
    out = tmp_path / "dry"
    assert R.main(dry(out, workers=2)) == 3
    summary = _stopped(out, stage_tables=True)
    assert "(2, 'BINANCE', '1x', 48)" in summary["status"]
    names = sorted(p.name for p in (out / "run0" / "blocks").glob("*.runs.parquet"))
    assert names == ["s1-KRAKEN-1x-00.runs.parquet", "s2-KRAKEN-2x-00.runs.parquet"]


def test_a_crash_is_recorded_and_re_raised(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)

    def crash(*args, **kwargs):
        raise KeyError("boom")

    monkeypatch.setattr(R, "write_outputs", crash)
    out = tmp_path / "dry"
    with pytest.raises(KeyError, match="boom"):
        R.main(dry(out))
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"].startswith("crashed: KeyError") and "Traceback" in summary["traceback"]
    assert [e.get("event") for e in runlog(out / "tracked" / "RUNLOG.jsonl")] == [None, "crashed"]
    assert (out / "run0" / "runs.parquet").exists()


# ------------------------------------------------------------------------------------- the decided dry run


@pytest.fixture(scope="module")
def decided(tmp_path_factory):
    """The --fast dry run (decision-capable: every mode and both readings) on 2 workers, with the boom checks
    allowed down to 1 window (the fast grid has 3 Kraken windows)."""
    root = tmp_path_factory.mktemp("decided")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(R, "TIMING_REPS_FAST", 1)
        mp.setattr(P, "BOOM_MIN_WINDOWS", 1)
        assert R.main(dry(root / "w2", workers=2)) == 0
    return root


def _load(root: Path) -> dict:
    return {
        "runs": pd.read_parquet(root / "run0" / "runs.parquet"),
        "stops": pd.read_parquet(root / "run0" / "stops.parquet"),
        "decision": read_json(root / "tracked" / "decision.json"),
        "csv": pd.read_csv(root / "tracked" / "runs.csv"),
        "start": read_json(root / "run0" / "start.json"),
        "summary": read_json(root / "run0" / "summary.json"),
    }


def test_workers_1_and_2_give_the_same_outputs_byte_for_byte(decided, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "BOOM_MIN_WINDOWS", 1)
    w1 = tmp_path / "w1"
    assert R.main(dry(w1, workers=1)) == 0
    for name in ("runs.csv", "decision.json"):
        assert (decided / "w2" / "tracked" / name).read_bytes() == (w1 / "tracked" / name).read_bytes(), name
    for name in ("runs", "stops"):
        a, b = (pd.read_parquet(root / "run0" / f"{name}.parquet") for root in (decided / "w2", w1))
        pd.testing.assert_frame_equal(a, b)
    assert (decided / "w2" / "run0" / "decision.json").read_bytes() == (
        decided / "w2" / "tracked" / "decision.json"
    ).read_bytes()


def _grid_ids(grid) -> set[str]:
    """Every run id the grid must log, from the plan's rules (section 6), not from run.py's loops."""
    ids = set()
    for k in grid.windows["KRAKEN"]:
        for s, f in grid.mixes:
            ids.add(f"1:KRAKEN:1x:{k}:{s:g}:{f:g}:R:-:none:none")
            for reading in ("separate", "counts"):
                for line in ("A", "B"):
                    for level in grid.levels[line]:
                        for mode in P.MODES:
                            ids.add(f"1:KRAKEN:1x:{k}:{s:g}:{f:g}:{line}:{level:g}:{mode}:{reading}")
    for source, cost in (("BINANCE", "1x"), ("KRAKEN", "2x")):
        for k in grid.windows[source]:
            for s, f in grid.mixes:
                ids.add(f"2:{source}:{cost}:{k}:{s:g}:{f:g}:R:-:none:none")
                for line in ("A", "B"):
                    for level in grid.levels[line]:
                        for mode in P.MODES:
                            ids.add(f"2:{source}:{cost}:{k}:{s:g}:{f:g}:{line}:{level:g}:{mode}:counts")
    return ids


def test_every_run_is_logged_and_each_run_s_numbers_come_from_its_configuration(decided):
    got = _load(decided / "w2")
    runs = got["runs"]
    assert set(runs["run_id"]) == _grid_ids(R.FAST) and len(runs) == len(_grid_ids(R.FAST)) == 544
    assert (runs["status"] == "ok").all() and got["summary"]["counts"] == {
        "stage1": 294,
        "stage2": 250,
        "total": 544,
    }
    assert got["decision"]["counts"]["stage1"] == {"got": 294, "expected": 294}
    loaded = panels()
    costs = {"1x": P.Costs.from_yaml(capital_usd=5000.0)}
    costs["2x"] = costs["1x"].stressed(2.0)
    windows = {s: {k: (a, z) for k, a, z in P.rolling_windows(s)} for s in H.SOURCES}
    stops = got["stops"]
    for i, row in enumerate(runs.itertuples(index=False)):
        if i % 9:
            continue
        first, last = windows[row.source][row.window]
        piece = H.window_slice(loaded[row.source], first, last, missing=H.MISSING_CLOSES[row.source])
        assert (row.first_close, row.last_close, row.rows) == (first, last, len(piece))
        signal = P.signal_rows(P.index_signal(loaded[row.source], row.f), piece.index)
        tp = P.tool_params(H.mix_targets(row.s, row.f), LIM)
        params = (
            tp
            if row.line == "R"
            else {**tp, "line": row.line, "level": row.level, "mode": row.mode, "reading": row.reading}
        )
        res = P.protect(params, piece, costs[row.cost], signal if row.line != "R" else None)
        measures, rows = P.run_measures(res, piece, costs[row.cost], signal if row.line != "R" else None)
        for key in (
            "F",
            "v_end",
            "stops",
            "buybacks",
            "restops",
            "usdc_share",
            "fees_pct_per_year_brake",
            "passes",
        ):
            assert getattr(row, key) == measures[key], (row.run_id, key)
        ref = runs[
            (runs["source"] == row.source)
            & (runs["cost"] == row.cost)
            & (runs["window"] == row.window)
            & (runs["s"] == row.s)
            & (runs["f"] == row.f)
            & (runs["line"] == "R")
            & (runs["stage"] == row.stage)
        ]
        assert row.C == 1.0 - measures["v_end"] / float(ref["v_end"].iloc[0])
        mine = stops[stops["run_id"] == row.run_id]
        assert mine["stop"].tolist() == [r["stop"] for r in rows]
        assert mine["overshoot"].tolist() == [r["overshoot"] for r in rows]


def test_runs_csv_is_one_row_per_run_with_no_return_column(decided):
    got = _load(decided / "w2")
    csv, runs = got["csv"], got["runs"]
    assert list(csv.columns) == list(R.CSV_COLUMNS) and len(csv) == len(runs)
    for bad in R.FORBIDDEN_CSV:
        assert bad not in csv.columns
    assert "F" in csv.columns and "C" in csv.columns
    np.testing.assert_allclose(csv["F"], runs["F"], rtol=1e-5)
    np.testing.assert_allclose(csv["C"], runs["C"], rtol=1e-5, atol=1e-12)
    assert csv["run_id"].tolist() == runs["run_id"].tolist()


# --- an independent statement of D1-D6 (written from PLAN.md section 8, sharing no code with protect.py)


def _p90(x) -> float:
    return float(np.percentile(np.asarray(x, dtype=float), 90))


def my_d1(pool, line, mode, reading):
    ref = pool[pool["line"] == "R"]
    rows = pool[(pool["line"] == line) & (pool["mode"] == mode) & (pool["reading"] == reading)]
    if rows.empty or (ref["status"] != "ok").any() or (rows["status"] != "ok").any():
        return "MISSING", {}
    q0 = _p90(ref["F"])
    mixes = sorted(set(zip(ref["s"], ref["f"], strict=True)))
    per = {}
    for level in sorted(set(rows["level"])):
        g = rows[rows["level"] == level]
        pooled = 3 * _p90(g["F"]) <= 2 * q0
        each = all(
            3 * _p90(g[(g["s"] == s) & (g["f"] == f)]["F"])
            <= 2 * _p90(ref[(ref["s"] == s) & (ref["f"] == f)]["F"])
            for s, f in mixes
        )
        guard = g["F"].max() <= ref["F"].max()
        bb, rs = int(g["buybacks"].sum()), int(g["restops"].sum())
        per[level] = {
            "ok": pooled and each and guard,
            "med": float(np.median(g["C"])),
            "mean": float(np.mean(g["C"])),
            "bb": bb,
            "share": rs / bb if bb else None,
        }
    if q0 == 0:
        return "NO DEFAULT", per
    ok = [lv for lv in per if per[lv]["ok"]]
    if not ok:
        return "NO DEFAULT", per
    low = min(per[lv]["med"] for lv in ok)
    tied = [lv for lv in ok if abs(per[lv]["med"] - low) <= 1e-12]
    tied.sort(key=lambda lv: (per[lv]["mean"], -lv if line == "A" else lv))
    return tied[0], per


def _le(a, b) -> bool:
    return a["mean"] <= b["mean"] if abs(a["med"] - b["med"]) <= 1e-12 else a["med"] < b["med"]


def _lt(a, b) -> bool:
    return a["mean"] < b["mean"] if abs(a["med"] - b["med"]) <= 1e-12 else a["med"] < b["med"]


def my_d2(pool, line, reading):
    d1 = {m: my_d1(pool, line, m, reading) for m in P.MODES}
    if any(d1[m][0] == "MISSING" for m in ("rebound-5", "rebound0", "rebound+5", "trend", "wait30")):
        return {"mode": "MISSING", "level": "MISSING"}, d1
    auto = []
    for m in ("rebound-5", "rebound0", "rebound+5", "trend"):
        level, per = d1[m]
        if isinstance(level, str):
            continue
        e = per[level]
        if e["share"] is not None and e["share"] <= 0.25:
            auto.append({"mode": m, "level": level, **e})
    best = None
    if auto:
        low = min(e["med"] for e in auto)
        tied = [e for e in auto if abs(e["med"] - low) <= 1e-12]
        order = ["trend", "rebound+5", "rebound0", "rebound-5"]
        best = sorted(tied, key=lambda e: (e["mean"], e["bb"], order.index(e["mode"])))[0]
    wl, wper = d1["wait30"]
    wait = None if isinstance(wl, str) else {"mode": "wait", "level": wl, **wper[wl]}
    if best and wait:
        pick = best if _le(best, wait) else wait
    else:
        pick = best or wait
    if pick is None:
        return {"mode": "NO DEFAULT", "level": "NO DEFAULT"}, d1
    return pick, d1


def test_decision_json_s_d1_to_d3_and_d6_are_recomputed_from_the_runs(decided):
    got = _load(decided / "w2")
    runs, decision = got["runs"], got["decision"]
    k1 = runs[(runs["source"] == "KRAKEN") & (runs["cost"] == "1x")]
    picks = {}
    for reading in ("separate", "counts"):
        mine = decision["stage1"]["by_reading"][reading]
        for line in ("A", "B"):
            pick, d1 = my_d2(k1, line, reading)
            picks[(reading, line)] = pick
            for mode in P.MODES:
                level, per = d1[mode]
                reported = mine["D1"][line][mode]
                assert reported["default"] == level, (reading, line, mode)
                for entry in reported["table"]:
                    e = per[entry["level"]]
                    assert (entry["meaningful"], entry["C_med"], entry["C_mean"]) == (
                        e["ok"],
                        e["med"],
                        e["mean"],
                    )
                    assert entry["restop_share"] == (e["share"] if e["share"] is not None else "MISSING")
            assert (mine["D2"][line]["mode"], mine["D2"][line]["level"]) == (pick["mode"], pick["level"])
        a, b = picks[(reading, "A")], picks[(reading, "B")]
        has = [x for x in (a, b) if not isinstance(x["level"], str)]
        if not has:
            want = "none"
        elif len(has) == 1:
            want = "A" if has[0] is a else "B"
        else:
            want = "A" if _le(a, b) else "B"
        assert mine["D3"]["line"] == want
    both = [
        line
        for line in ("A", "B")
        if all(not isinstance(picks[(r, line)]["level"], str) for r in ("separate", "counts"))
    ]
    sep = bool(both) and all(_lt(picks[("separate", line)], picks[("counts", line)]) for line in both)
    assert decision["stage1"]["D6"]["recommended"] == ("separate" if sep else "counts")
    assert (
        decision["stage1"]["D6"]["in_force"] == "counts"
        and decision["headline"]["reading_in_force"] == "counts"
    )


def _key(pick, line):
    return pick["level"] if isinstance(pick["level"], str) else [line, pick["mode"], pick["level"]]


def test_d4_s_checks_and_labels_are_recomputed_from_the_runs(decided):
    got = _load(decided / "w2")
    runs, decision, start = got["runs"], got["decision"], got["start"]
    returns = {int(k): v for k, v in start["year_returns"].items()}
    best = sorted(returns, key=lambda y: (-returns[y], y))
    k1 = runs[(runs["source"] == "KRAKEN") & (runs["cost"] == "1x")]
    pools = {}  # D4's checks in the plan's order: the boom years, Binance, 2x costs
    for n in (1, 2):
        years = best[:n]
        kept = [
            k
            for k in (0, 24, 48)
            if not any(12 * (y - 2017) - 23 <= k <= 12 * (y - 2017) + 11 for y in years)
        ]
        boom = decision["stage2"]["checks"]["boom"][f"boom: without the best {n}"]
        assert boom["years"] == years and boom["windows"] == kept
        pools[f"boom: without the best {n}"] = k1[k1["window"].isin(kept)] if kept else None
    pools["Binance"] = runs[(runs["source"] == "BINANCE") & (runs["cost"] == "1x")]
    pools["2x costs"] = runs[(runs["source"] == "KRAKEN") & (runs["cost"] == "2x")]
    labels = decision["stage2"]["D4"]
    head = {line: _key(my_d2(k1, line, "counts")[0], line) for line in ("A", "B")}
    for line in ("A", "B"):
        moved, missing = [], []
        for name, pool in pools.items():
            if pool is None:
                missing.append(name)
                continue
            theirs = _key(my_d2(pool, line, "counts")[0], line)
            assert labels[line]["checks"][name] == theirs, (line, name)
            if theirs == "MISSING":
                missing.append(name)
            elif theirs != head[line]:
                moved.append(name)
        assert labels[line]["default"] == head[line]
        if moved:
            assert labels[line]["label"].startswith("NOT ROBUST (") and labels[line]["moved"] == moved
        elif missing:
            assert labels[line]["label"] == f"MISSING ({', '.join(missing)})"
        else:
            assert labels[line]["label"] == "ROBUST"


def test_d5_and_the_stops_at_the_defaults_are_recomputed_from_the_stops(decided):
    got = _load(decided / "w2")
    runs, stops, decision = got["runs"], got["stops"], got["decision"]
    k1 = runs[
        (runs["source"] == "KRAKEN") & (runs["cost"] == "1x")
    ]  # the reference runs too (reading "none")
    for line in ("A", "B"):
        pick, _ = my_d2(k1, line, "counts")
        d5 = decision["stage2"]["D5"][line]
        listed = decision["stage2"]["stops_at_defaults"][line]
        if isinstance(pick["level"], str):
            assert d5["status"] == "MISSING" and listed == []
            continue
        basis = "wait30" if pick["mode"] == "wait" else pick["mode"]
        at = k1[
            (k1["line"] == line)
            & (k1["mode"] == basis)
            & (k1["level"] == pick["level"])
            & (k1["reading"] == "counts")
        ]
        mine = stops[stops["run_id"].isin(at["run_id"])]
        assert len(listed) == len(mine)
        if mine.empty:
            assert d5["status"] == "MISSING"
            continue
        assert d5["Z"] == mine["overshoot"].max()
        assert d5["Z_p95"] == float(np.percentile(mine["overshoot"], 95)) and d5["worst_F"] == at["F"].max()
        below = mine[mine["below_d"]]["sale_vs_d"]
        if line == "B":
            assert d5["b_worst_below_d"] == (below.min() if len(below) else "none")
        assert [s["stop_ts"] for s in listed] == [t.isoformat() for t in mine["stop_ts"]]


def test_the_level_tables_are_recomputed_from_the_runs(decided):
    got = _load(decided / "w2")
    runs, stops, decision = got["runs"], got["stops"], got["decision"]
    for name, (source, cost) in {
        "KRAKEN 1x": ("KRAKEN", "1x"),
        "BINANCE 1x": ("BINANCE", "1x"),
        "KRAKEN 2x": ("KRAKEN", "2x"),
    }.items():
        table = decision["stage2"]["tables"][name]
        pool = runs[(runs["source"] == source) & (runs["cost"] == cost)]
        groups = pool.groupby(["line", "level", "mode", "reading"], dropna=False)
        assert len(table) == groups.ngroups
        for entry in table:
            if entry["line"] == "R":
                g = pool[pool["line"] == "R"]
            else:
                g = pool[
                    (pool["line"] == entry["line"])
                    & (pool["level"] == entry["level"])
                    & (pool["mode"] == entry["mode"])
                    & (pool["reading"] == entry["reading"])
                ]
            st = stops[stops["run_id"].isin(g["run_id"])]
            assert entry["runs"] == len(g) and entry["stops"] == int(g["stops"].sum()) == len(st)
            assert entry["fire_rate"] == float(g["fired"].mean()) and entry["Q"] == _p90(g["F"])
            assert entry["distinct_sale_dates"] == st["stop_ts"].nunique()
            assert entry["C_med"] == float(np.median(g["C"]))
            for (s, f), gm in g.groupby(["s", "f"]):
                mix = f"{s:g}/{f:g}"
                assert entry["fire_rate_mix"][mix] == float(gm["fired"].mean()) and entry["Q_mix"][
                    mix
                ] == _p90(gm["F"])
                assert entry["C_med_mix"][mix] == float(np.median(gm["C"]))
            active = g[g["b_active"]]
            assert entry["b_active_runs"] == len(active)
            assert entry["b_kept_end_median"] == (
                float(np.median(active["b_kept_end"])) if len(active) else None
            )


def test_stage_2_runs_the_reading_in_force_only(decided):
    got = _load(decided / "w2")
    runs = got["runs"]
    stage2 = runs[runs["stage"] == 2]
    assert set(stage2["reading"]) == {"none", "counts"} and set(stage2["cost"]) == {"1x", "2x"}
    assert set(zip(stage2["source"], stage2["cost"], strict=True)) == {("BINANCE", "1x"), ("KRAKEN", "2x")}
    assert got["summary"]["stage2_reading"] == "counts"
    stage1 = runs[runs["stage"] == 1]
    assert set(stage1["reading"]) == {"none", "separate", "counts"} and set(stage1["source"]) == {"KRAKEN"}


def test_stage_2_runs_the_reading_in_force_even_when_d6_recommends_separate(tmp_path, monkeypatch):
    """D6 only recommends: 'counts' stays in force until the owner approves 'separate' in writing, so stage 2 and the
    reported defaults are 'counts''s even when 'separate' is recommended."""
    real = P.d6

    def recommends_separate(d2s):
        return {**real(d2s), "recommended": "separate", "needs_owner_approval": True}

    monkeypatch.setattr(P, "d6", recommends_separate)
    small = R.Grid(
        mixes=((0.5, 0.5),),
        levels={"A": (0.10,), "B": (0.40,)},
        modes=P.MODES,
        readings=P.READINGS,
        windows={"KRAKEN": (0,), "BINANCE": (48,)},
        name="test-small",
    )
    monkeypatch.setattr(R, "FAST", small)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    assert set(runs[runs["stage"] == 2]["reading"]) == {"none", "counts"}
    decision = read_json(out / "run0" / "decision.json")
    assert (
        decision["stage1"]["D6"]["recommended"] == "separate"
        and decision["stage1"]["D6"]["in_force"] == "counts"
    )
    assert (
        decision["headline"]["reading_in_force"] == "counts"
        and decision["headline"]["D6_recommended"] == "separate"
    )
    assert read_json(out / "run0" / "summary.json")["stage2_reading"] == "counts"
