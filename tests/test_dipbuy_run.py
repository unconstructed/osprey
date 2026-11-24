"""The buy-the-dip study script (``research/buy-the-dip/run.py``) against PLAN.md sections 3-14: the start guards, the
start record and RUNLOG line before any bar, the data stops, every run logged, each consistency stop of section 10, the
two stages, and every reported number recomputed from its inputs.

SYNTHETIC data only: every run is a ``--synthetic`` dry run in ``tmp_path`` (``--fast``, or a tiny grid put in its
place), the real catalog loader is replaced by one that fails the test if it is ever reached (except where a test
hands it synthetic bars on purpose), and the git state is injected where a test needs one. Real-data guards run
against stand-ins for every folder a real run uses (``real_folders``), so the repo's recorded runs never decide which
guard a test reaches (TESTING.md #48); no test reads the committed PLAN.md's amendments or the real
``config/risk_levels.yaml``'s budget beyond what section 4 pins (#55, #59, #68).
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
from test_dipbuy import make_pool
from test_portfolio import edit_steady_entry, set_steady_budget

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.panel import load_panel
from lab.runner import dipbuy as DB
from lab.runner import holdmix as H
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner.reference import Costs
from lab.runner.steady import panel_hash

STUDY_DIR = Path(__file__).resolve().parents[1] / "research" / "buy-the-dip"
NAME = "buy_the_dip_run"
if NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(NAME, STUDY_DIR / "run.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[NAME] = _module
    _spec.loader.exec_module(_module)
R = sys.modules[NAME]

CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
SEED = 7
DECIDED_SEED = 1  # the --fast dry run on seed 1 has a default (a setting), so D3 and D2's moves are exercised
LIM = {"min_cash": 0.20, "max_coin": 0.60}
FAST = R.FAST  # the script's own --fast grid (tests may put TINY in its place)
TINY_TIMING = {"cpu_minutes": 1.0, "wall_minutes_on_2_workers": 0.5, "reps": 1}
# The smallest complete dry run, for tests about the guards and the bookkeeping rather than the rules
TINY = R.Grid(
    settings=((0.10, 0.05, 0.10, 1.00),),
    starts=((0.0, 0.50),),
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


def dry(out: Path, *extra: str, workers: int = 1, fast: bool = True, seed: int = SEED) -> list[str]:
    return [
        "--synthetic",
        str(seed),
        *(["--fast"] if fast else []),
        "--out-dir",
        str(out),
        "--workers",
        str(workers),
        *extra,
    ]


def real_folders(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Stand-ins for results/buy-the-dip, data/catalog and this study's folder (the tracked RUNLOG and copies)."""
    out, cat, here = tmp_path / "results" / "buy-the-dip", tmp_path / "data" / "catalog", tmp_path / "here"
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
    assert (c["stage1"], c["stage2"], c["total"]) == (31_948, 58_680, 90_628)  # section 7
    assert c["stage1"] == 163 * 4 * 49 and c["stage2"] == 163 * 4 * (41 + 49) and c["per_start_window"] == 163
    assert c["dip"] == c["dca"] == c["lump"] == 54 * 4 * 139 and c["hold"] == 4 * 139
    assert c["dip"] * 3 + c["hold"] == 90_628
    g = R.PLAN_GRID
    assert (
        g.settings == tuple(tuple(s) for s in DB.SETTINGS) and g.starts == DB.STARTS and len(g.settings) == 54
    )
    assert g.windows == {"KRAKEN": tuple(range(49)), "BINANCE": tuple(range(8, 49))} and g.decidable
    f = R.FAST
    assert f.decidable and len(f.settings) == 4 and len(f.starts) == 2
    assert {s[0] for s in f.settings} == set(DB.Y_VALUES) and {s[1] for s in f.settings} == set(DB.Z_VALUES)
    assert {s[2] for s in f.settings} == set(DB.X_VALUES) and {s[3] for s in f.settings} == set(DB.M_VALUES)
    fast = R.expected_counts(f)
    assert (fast["stage1"], fast["stage2"]) == (13 * 2 * 3, 13 * 2 * (2 + 3))
    assert R.expected_counts(TINY)["stage1"] == 4 and R.expected_counts(TINY)["stage2"] == 8
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
    assert R.PANEL_HASHES == {
        "KRAKEN": "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
        "BINANCE": "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
    }
    assert R.STAGE1_POOL == ("KRAKEN", "1x") and R.STAGE2_POOLS == (("BINANCE", "1x"), ("KRAKEN", "2x"))
    assert R.TIMING_BUSY == (0.10, 0.05, 0.10, 1.00) and R.TIMING_START == (0.0, 0.5) and R.TIMING_ROWS == 731
    assert R.BOOK_CHECK_EVERY == 9
    assert [R.block_name(t) for t in R.tasks(R.PLAN_GRID, 1)][:2] == ["s1-KRAKEN-1x-00", "s1-KRAKEN-1x-01"]
    assert len(R.tasks(R.PLAN_GRID, 1)) == 49 and len(R.tasks(R.PLAN_GRID, 2)) == 41 + 49


def test_the_hashed_files_and_the_config_hash_move_with_them(tmp_path):
    paths = R.frozen_paths()
    for listed in (  # section 10's list
        "lab/runner/dipbuy.py",
        "lab/runner/protect.py",
        "lab/runner/portfolio.py",
        "lab/runner/holdmix.py",
        "lab/runner/reference.py",
        "lab/runner/trend.py",
        "lab/validation/montecarlo.py",
        "lab/validation/stats.py",
        "lab/data/panel.py",
        "lab/data/catalog.py",
        "lab/data/loaders.py",
        "config/costs.yaml",
        "config/splits.yaml",
        "config/risk_levels.yaml",
        "pyproject.toml",
        "uv.lock",
        "research/buy-the-dip/run.py",
        "research/buy-the-dip/PLAN.md",
    ):
        assert listed in paths, listed
    assert paths == sorted(paths) and not any("protect-gains" in p for p in paths)
    hashes = R.file_hashes()
    assert (
        hashes["lab/runner/dipbuy.py"]
        == hashlib.sha256((R.REPO / "lab/runner/dipbuy.py").read_bytes()).hexdigest()
    )
    base = R.config_hash(hashes)
    assert R.config_hash(dict(reversed(list(hashes.items())))) == base
    assert R.config_hash({**hashes, "lab/runner/dipbuy.py": "0" * 64}) != base
    cfg = copy_config(tmp_path / "cfg")
    assert R.file_hashes(cfg) == hashes
    # a budget-only change from TBD to 30, whatever the real file holds (#55, #74)
    set_steady_budget(cfg, "TBD")
    tbd = R.file_hashes(cfg)
    assert [k for k in hashes if hashes[k] != tbd[k]] in ([], ["config/risk_levels.yaml"])
    set_steady_budget(cfg, "30")
    moved = R.file_hashes(cfg)
    assert [k for k in tbd if tbd[k] != moved[k]] == ["config/risk_levels.yaml"]
    pinned = R.pinned_values()
    assert pinned["limits"] == {"min_cash": 0.2, "max_coin": 0.6} and pinned["deposit"] == 5000.0
    assert pinned["high_days"] == 365 and pinned["dca"] == {"pieces": 12, "days": 30}
    assert len(pinned["windows"]["KRAKEN"]) == 49 and len(pinned["windows"]["BINANCE"]) == 41
    assert pinned["readings"] == R.jsonable(DB.READINGS_PINNED) and pinned["book_check_every"] == 9


def test_amendment_rows_are_read_from_section_12_s_list_only():
    plan = "x\n**Amendments:**\n- **R1 (2026-11-24):** ...\n- **Amendment run 1 (2026-12-01): a bug**\n## 13. Allowed\n"
    assert R.amendment_row_present(plan, 1) and not R.amendment_row_present(plan, 2)
    assert not R.amendment_row_present(plan.replace("## 13.", "13."), 1)
    assert not R.amendment_row_present("- **Amendment run 1**\n**Amendments:**\n## 13.\n", 1)
    assert not R.amendment_row_present("## 13.\n**Amendments:**\n- **Amendment run 1**\n", 1)
    assert not R.amendment_row_present(plan.replace("run 1 ", "run 10 "), 1)
    assert R.amendment_row_present(plan.replace("**Amendments:**", "**Amendments**"), 1)


def test_the_out_dir_and_real_path_guards_by_hand(tmp_path, monkeypatch):
    for bad in (R.DEFAULT_OUT, R.DEFAULT_OUT / "x", R.REPO / "scratch", R.REPO):
        with pytest.raises(R.Refusal, match="never writes into"):
            R.check_out_dir(bad)
    R.check_out_dir(tmp_path / "scratch")
    out, cat, _ = real_folders(monkeypatch, tmp_path)
    R.check_real_paths(out, None, cat)
    R.check_real_paths(out, R.REPO / "config", cat)
    for args, what in (
        ((tmp_path / "elsewhere", None, cat), "--out-dir"),
        ((out, tmp_path / "cfg", cat), "--config-dir"),
        ((out, None, tmp_path / "cat2"), "--catalog-dir"),
    ):
        with pytest.raises(R.Refusal, match=what):
            R.check_real_paths(*args)


def test_jsonable_and_run_ids_and_the_sort_order():
    assert R.jsonable(
        {1.5: [np.float64("nan"), np.int64(3), pd.NaT, pd.Timestamp("2020-01-01", tz="UTC")]}
    ) == {"1.5": [None, 3, None, "2020-01-01T00:00:00+00:00"]}
    assert R.jsonable((np.bool_(True), np.array([1.0, math.inf]))) == [True, [1.0, None]]
    assert R.run_id(1, "KRAKEN", "1x", 3, 0.3, 0.75, "dip", (0.1, 0.05, 0.25, 1.0)) == (
        "1:KRAKEN:1x:3:0.3:0.75:dip:0.1:0.05:0.25:1"
    )
    assert R.run_id(2, "BINANCE", "1x", 8, 0.0, 0.5, "hold") == "2:BINANCE:1x:8:0:0.5:hold:-:-:-:-"
    frame = pd.DataFrame(
        {
            "stage": [1] * 5,
            "source": ["KRAKEN"] * 5,
            "cost": ["1x"] * 5,
            "window": [0] * 5,
            "s0": [0.0] * 5,
            "f": [0.5] * 5,
            "Y": [0.2, 0.1, 0.1, math.nan, 0.1],
            "Z": [0.1, 0.1, 0.1, math.nan, 0.1],
            "X": [0.1] * 4 + [0.1],
            "M": [0.25] * 5,
            "kind": ["dip", "lump", "dip", "hold", "dca"],
        }
    )
    got = R.sort_rows(frame)
    assert list(zip(got["kind"], got["Y"].fillna(-1), strict=True)) == [
        ("hold", -1),
        ("dip", 0.1),
        ("dca", 0.1),
        ("lump", 0.1),
        ("dip", 0.2),
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
    late = got["KRAKEN"].copy()
    late.index = late.index + pd.Timedelta(days=1)  # 2190 rows ending 2023-01-02
    late.attrs = got["KRAKEN"].attrs
    with pytest.raises(R.Stop, match="stop rule 3: KRAKEN: a close 2023-01-02"):
        R.check_panel("KRAKEN", late, synthetic=True)


def test_the_timing_projects_the_plan_s_grid_by_hand():
    t = R.measure_throughput(LIM, None, 1)
    counts = R.expected_counts(R.PLAN_GRID)
    assert t["runs"] == {"hold": 556, "dip": 30_024, "dca": 30_024, "lump": 30_024}
    want = sum(counts[k] * t["seconds_per_run"][k] for k in DB.KINDS) / 60.0
    assert t["cpu_minutes"] == pytest.approx(want, rel=1e-12) and t["limit_cpu_minutes"] == 240.0
    assert (
        t["busy_shape"]["ladders"] >= 1 and t["busy_shape"]["orders"] >= 5
    )  # the busy setting buys on the panel
    assert t["wall_minutes_on_2_workers"] == pytest.approx(t["cpu_minutes"] / 2.0, rel=1e-12)


def test_time_mode_writes_its_projection_to_a_scratch_folder_only(tmp_path, capsys):
    out = tmp_path / "timing"
    assert R.main(["--time", "--out-dir", str(out)]) == 0
    assert read_json(out / "timing.json")["timing"]["runs"]["dip"] == 30_024
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
    results = R.REPO / "results" / "buy-the-dip"
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
        "ladders.parquet",
        "runs.parquet",
        "start.json",
        "summary.json",
    ]
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"] == "complete" and summary["counts"] == {"stage1": 4, "stage2": 8, "total": 12}
    assert read_json(out / "run0" / "decision.json")["stage1"] is not None


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


def test_git_state_counts_untracked_files_but_not_ignored_ones(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=repo, check=True)
    assert R.git_state(repo)["dirty"] is False
    (repo / "ignored.txt").write_text("x")
    assert R.git_state(repo)["dirty"] is False
    (repo / "new").mkdir()
    (repo / "new" / "run.py").write_text("x")
    got = R.git_state(repo)
    assert got["dirty"] is True and got["changes"] == ["?? new/run.py"]
    (tmp_path / "plain").mkdir()
    with pytest.raises(RuntimeError, match="failed"):
        R.git_state(tmp_path / "plain")


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
    monkeypatch.setattr(R, "PLAN_GRID", TINY)  # a broken guard below must not start the plan's 90,628 runs
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
    plan = tmp_path / "PLAN.md"
    plan.write_text("**Amendments:**\n- **R1 (2026-11-24):** caps\n- **A1:** timing\n## 13. Allowed\n")
    monkeypatch.setattr(R, "PLAN", plan)
    assert R.main(real_args(out, cat, "--amendment", "1")) == 2
    assert "lists no '- **Amendment run 1' row" in capsys.readouterr().err
    plan.write_text("**Amendments:**\n- **Amendment run 1 (2026-12-01): a bug**\n## 13. x\n")
    assert R.main(real_args(out, cat, "--amendment", "1")) == 2
    assert "bars hash" in capsys.readouterr().err  # the next guard


@pytest.mark.parametrize(
    ("old", "new", "msg"),
    [
        ("min_cash_pct: 20", "min_cash_pct: 21", "min_cash 0.21"),
        ("max_coin_pct: 60", "max_coin_pct: 55", "max_coin 0.55"),
        ("  min_cash_pct: 20\n", "", "min_cash None"),
        ("  max_coin_pct: 60\n", "", "max_coin None"),
    ],
)
def test_steady_limits_other_than_the_plan_s_are_refused(tmp_path, old, new, msg, capsys):
    cfg = copy_config(tmp_path / "cfg")
    edit_steady_entry(cfg, old, new)
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(cfg))) == 2
    err = capsys.readouterr().err
    assert msg in err and "not the plan's 0.2 and 0.6" in err and not (tmp_path / "dry").exists()


def test_a_risk_levels_file_that_does_not_read_or_a_start_the_limits_refuse_stop_the_start(
    tmp_path, monkeypatch, capsys
):
    bad = copy_config(tmp_path / "bad")
    (bad / "risk_levels.yaml").write_text("steady: [1, 2]\n")
    assert R.main(dry(tmp_path / "dry", "--config-dir", str(bad))) == 2
    assert "does not read" in capsys.readouterr().err
    monkeypatch.setattr(R, "FAST", R.Grid(settings=TINY.settings, starts=((0.9, 0.5),), windows=TINY.windows))
    assert R.main(dry(tmp_path / "dry")) == 2
    assert "refuse a start wallet" in capsys.readouterr().err and not (tmp_path / "dry").exists()


def test_the_budget_is_read_and_recorded_not_enforced(tmp_path, tiny):
    cfg = copy_config(tmp_path / "cfg")
    set_steady_budget(cfg, "TBD")
    assert R.main(dry(tmp_path / "a", "--config-dir", str(cfg))) == 0
    assert read_json(tmp_path / "a" / "run0" / "decision.json")["budget"] is None
    set_steady_budget(cfg, "10")
    assert R.main(dry(tmp_path / "b", "--config-dir", str(cfg))) == 0
    assert read_json(tmp_path / "b" / "run0" / "decision.json")["budget"] == 0.1


def test_the_catalog_snapshot_is_checked_before_any_bar(tmp_path, monkeypatch, clean_git, capsys):
    out, cat, _ = real_folders(monkeypatch, tmp_path)
    assert R.main(real_args(out, cat)) == 2
    assert "cannot read" in capsys.readouterr().err
    write_snapshot(cat, snapshot_id="")
    assert R.main(real_args(out, cat)) == 2
    assert "names no snapshot_id" in capsys.readouterr().err
    assert not out.exists()
    assert R.read_snapshot(cat.parent / "x", synthetic=True)["plan_snapshot_id"] == "1746a21b75683e76"
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

    monkeypatch.setattr(DB, "dip_buy", broken)
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
    assert start["risk_limits"]["min_cash"] == 0.2 and start["risk_limits"]["max_coin"] == 0.6
    assert start["interpretations"] == R.jsonable(R.INTERPRETATIONS)
    assert start["windows"]["KRAKEN"][0] == [0, "2017-01-02T00:00:00+00:00", "2019-01-01T00:00:00+00:00"]
    assert start["costs"]["2x"]["gas_usd_per_trade"] == 2 * start["costs"]["1x"]["gas_usd_per_trade"]
    assert start["costs"]["1x"]["capital_usd"] == 5000.0
    assert start["config_hash"] == R.config_hash(R.file_hashes())
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
    def factory(seed):
        inner = ORIGINAL_LOADER(seed)

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
    def factory(seed):
        inner = ORIGINAL_LOADER(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            got = change(instrument, bars)
            got.attrs = bars.attrs
            return got

        return loader

    return factory


def test_a_wrong_row_count_or_a_window_close_missing_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    monkeypatch.setattr(
        R, "synthetic_bar_loader", _reshaped(lambda inst, bars: bars.iloc[1:] if "KRAKEN" in inst else bars)
    )
    assert R.main(dry(tmp_path / "a")) == 3
    summary = read_json(tmp_path / "a" / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "2189 rows, expected 2190" in summary["status"]
    assert (
        read_json(tmp_path / "a" / "run0" / "start.json")["panels"]["KRAKEN"]["rows"] == 2189
    )  # recorded first
    gone, extra = pd.Timestamp("2017-09-10", tz="UTC"), pd.Timestamp("2017-08-17", tz="UTC")

    def swap(
        inst, bars
    ):  # a Binance close missing inside window 8, with an extra bar before it: still 1963 rows
        if "BINANCE" not in inst:
            return bars
        row = bars.iloc[[0]].copy()
        row.index = pd.DatetimeIndex([extra], name="ts").as_unit("us")
        return pd.concat([row, bars.drop(gone)])

    monkeypatch.setattr(R, "synthetic_bar_loader", _reshaped(swap))
    assert R.main(dry(tmp_path / "b")) == 3
    summary = read_json(tmp_path / "b" / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "BINANCE window 8" in summary["status"]


def test_a_binance_panel_with_an_extra_row_stops_the_run(tmp_path, monkeypatch):
    """Section 3's 1963 Binance rows: an extra close before 2017-08-18 leaves every window whole (it feeds only I and
    H), so only the row count can stop it (#74)."""
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))

    def extra(inst, bars):
        if "BINANCE" not in inst:
            return bars
        row = bars.iloc[[0]].copy()
        row.index = pd.DatetimeIndex([pd.Timestamp("2017-08-17", tz="UTC")], name="ts").as_unit("us")
        return pd.concat([row, bars])

    monkeypatch.setattr(R, "synthetic_bar_loader", _reshaped(extra))
    assert R.main(dry(tmp_path / "a")) == 3
    summary = read_json(tmp_path / "a" / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "BINANCE: 1964 rows, expected 1963" in summary["status"]


def test_real_data_with_other_bars_stops_the_run(tmp_path, monkeypatch, clean_git, tiny):
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(TINY_TIMING))
    monkeypatch.setattr(catalog, "load_bars", R.synthetic_bar_loader(SEED))  # on purpose: other bars
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out, cat, _ = real_folders(monkeypatch, tmp_path / "a")
    write_snapshot(cat)
    assert R.main(real_args(out, cat)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "KRAKEN: panel hash" in summary["status"]
    # with Kraken's hash the expected one, Binance's own hash is checked and stops the run (#74)
    monkeypatch.setitem(R.PANEL_HASHES, "KRAKEN", panel_hash(panels(SEED)["KRAKEN"]))
    out, cat, _ = real_folders(monkeypatch, tmp_path / "b")
    write_snapshot(cat)
    assert R.main(real_args(out, cat)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "BINANCE: panel hash" in summary["status"]


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


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("check_events", "a broken events check"),
        ("check_order_targets", "a broken R1 check"),
        ("check_twin", "a broken twin check"),
        ("check_values", "a broken book check"),
    ],
)
def test_each_run_check_stops_the_run(tmp_path, monkeypatch, tiny, target, message):
    _stub_timing(monkeypatch)

    def raising(*args, **kwargs):
        raise DB.ConsistencyError(message)

    monkeypatch.setattr(DB, target, raising)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert message in _stopped(out)["status"]


def test_the_accounting_runs_on_every_9th_run_and_its_failure_stops_the_run(tmp_path, monkeypatch):
    _stub_timing(monkeypatch)
    calls = []
    real = P.check_book

    def counting(result, bars, costs, tol=1e-12):
        calls.append(result.attrs["kind"])
        return real(result, bars, costs, tol)

    monkeypatch.setattr(P, "check_book", counting)
    many = R.Grid(settings=FAST.settings, starts=((0.0, 0.5),), windows={"KRAKEN": (0,), "BINANCE": (48,)})
    monkeypatch.setattr(R, "FAST", many)
    assert R.main(dry(tmp_path / "a")) == 0
    per_block = 3 * 4 + 1  # hold, then dip, dca, lump per setting: runs 0 and 9 of each block are checked
    assert len(calls) == 3 * math.ceil(per_block / 9) and calls[:2] == ["hold", "lump"]

    def broken(*args, **kwargs):
        raise DB.ConsistencyError("the return or value on row 4 differs from the book")

    monkeypatch.setattr(P, "check_book", broken)
    assert R.main(dry(tmp_path / "b")) == 3
    assert "differs from the book" in _stopped(tmp_path / "b")["status"]


def test_a_failing_fee_check_stops_the_run(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)

    def broken(result, costs):
        raise H.ConsistencyError("customer fees + gas differ from the cost column")

    monkeypatch.setattr(H, "money_metrics", broken)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "differ from the cost column" in _stopped(out)["status"]


def test_ladder_decisions_that_move_with_costs_stop_the_run(tmp_path, monkeypatch, tiny):
    """Section 10: a Kraken dip run whose triggers, crossings or re-arms differ between 1x and 2x stops the run
    (stop rule 5), after both stages' tables are written."""
    _stub_timing(monkeypatch)
    real = R._block

    def moved(stage, source, cost, k):
        got = real(stage, source, cost, k)
        if cost == "2x":
            i = got["runs"].index[got["runs"]["kind"] == "dip"][0]
            got["runs"].loc[i, "events_hash"] = "0" * 64
        return got

    monkeypatch.setattr(R, "_block", moved)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    status = _stopped(out, stage_tables=True)["status"]
    assert "1 Kraken dip runs' triggers, crossings or re-arms differ between 1x and 2x" in status
    assert "1:KRAKEN:1x:0:0:0.5:dip:0.1:0.05:0.1:1" in status


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
    assert "stage 2 logged 7 runs, expected 8" in _stopped(out, stage_tables=True)["status"]


def test_a_lost_stage_1_run_stops_the_run_before_stage_2(tmp_path, monkeypatch, tiny):
    """Section 10's 31,948: stage 1's own count (check_counts(runs, grid, 2) counts stage-2 rows only). A lost hold row
    would leave D1 runnable on a short pool, so it must stop the run before stage 2 (#74)."""
    _stub_timing(monkeypatch)
    real = R._block

    def lossy(stage, source, cost, k):
        got = real(stage, source, cost, k)
        if stage == 1:
            got["runs"] = got["runs"][got["runs"]["kind"] != "hold"]
        return got

    monkeypatch.setattr(R, "_block", lossy)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = _stopped(out, stage_tables=True)  # stage 1's tables are written before its count
    assert "stage 1 logged 3 runs, expected 4" in summary["status"] and "stage2" not in summary["grid"]
    names = sorted(p.name for p in (out / "run0" / "blocks").glob("*.runs.parquet"))
    assert names == ["s1-KRAKEN-1x-00.runs.parquet"]


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
        return got if len(calls) == 1 else {**got, "lab/runner/dipbuy.py": "0" * 64}

    monkeypatch.setattr(R, "file_hashes", moving)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "a hashed file changed during the run" in _stopped(out, stage_tables=True)["status"]


def test_a_failed_dip_run_is_logged_with_its_twins_and_the_grid_goes_on(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = DB.dip_buy

    def failing(params, bars, costs=None, signal=None, **kw):
        if params["kind"] == "dip" and bars.index[0] == pd.Timestamp("2017-01-02", tz="UTC"):
            raise RuntimeError("a synthetic failure")
        return real(params, bars, costs, signal, **kw)

    monkeypatch.setattr(DB, "dip_buy", failing)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    failed = runs[runs["status"] != "ok"]
    assert sorted(failed["run_id"]) == sorted(
        f"{s}:KRAKEN:{c}:0:0:0.5:{k}:0.1:0.05:0.1:1"
        for s, c in ((1, "1x"), (2, "2x"))
        for k in ("dip", "dca", "lump")
    )
    dips = failed[failed["kind"] == "dip"]
    assert (dips["error"] == "RuntimeError: a synthetic failure").all() and failed["F"].isna().all()
    assert (failed[failed["kind"] != "dip"]["error"].str.startswith("the dip run failed")).all()
    assert (failed["orders"] == -1).all() and len(runs) == 12
    failures = pd.read_parquet(out / "run0" / "failures.parquet")
    assert (
        len(failures) == 6
        and "Traceback" in failures[failures["run_id"].str.contains(":dip:")]["traceback"].iloc[0]
    )
    decision = read_json(out / "run0" / "decision.json")
    assert decision["failed_runs"] == 6 and decision["stage1"]["D1"]["default"] == DB.MISSING
    csv = pd.read_csv(out / "tracked" / "runs.csv")
    assert len(csv) == 12 and (csv["status"] == "failed").sum() == 6


def test_a_failed_twin_leaves_its_dip_run_without_comparisons(tmp_path, monkeypatch, tiny):
    _stub_timing(monkeypatch)
    real = DB.dip_buy

    def failing(params, bars, costs=None, signal=None, **kw):
        if params["kind"] in ("lump", "hold") and bars.index[0] == pd.Timestamp("2021-01-02", tz="UTC"):
            raise RuntimeError("a twin failure")
        return real(params, bars, costs, signal, **kw)

    monkeypatch.setattr(DB, "dip_buy", failing)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    binance = runs[runs["source"] == "BINANCE"]
    assert sorted(binance[binance["status"] != "ok"]["kind"]) == ["hold", "lump"]
    dip = binance[binance["kind"] == "dip"].iloc[0]
    assert dip["status"] == "ok" and math.isnan(dip["T_dca"]) and math.isnan(dip["G"])


NEVER = R.Grid(  # a ladder that never triggers on the synthetic bars (a 99% fall from the year's high)
    settings=((0.99, 0.05, 0.10, 1.00),),
    starts=((0.0, 0.50), (0.30, 0.75)),
    windows={"KRAKEN": (0,), "BINANCE": (48,)},
    name="test-never",
)


def test_a_dip_run_with_no_order_has_its_twins_checked_against_hold(tmp_path, monkeypatch):
    """Section 10: a dip run whose ladder ordered nothing has twins equal to hold bit for bit. run.py checks it only
    by handing the window's and start's hold run to check_twin; the dry runs of the --fast grid all order something,
    so this grid never triggers (#74)."""
    _stub_timing(monkeypatch)
    monkeypatch.setattr(R, "FAST", NEVER)
    calls, real = [], DB.check_twin

    def spy(twin, total, hold=None):
        calls.append((twin.attrs["kind"], total, hold))
        return real(twin, total, hold)

    monkeypatch.setattr(DB, "check_twin", spy)
    assert R.main(dry(tmp_path / "a")) == 0
    assert len(calls) == 2 * 2 * 3  # dca and lump, 2 starts, 3 pools of one window each
    for kind, total, hold in calls:
        assert total == 0.0 and hold is not None and hold.attrs["kind"] == "hold", kind
    runs = pd.read_parquet(tmp_path / "a" / "run0" / "runs.parquet")
    assert (runs[runs["kind"] == "dip"]["ordered_usd"] == 0.0).all()
    for _, g in runs.groupby(["source", "cost", "window", "s0", "f"]):
        (hold,) = g[g["kind"] == "hold"]["orders_hash"]
        assert sorted(g[g["kind"].isin(["dca", "lump"])]["orders_hash"]) == [hold, hold]
    # a hold result that differs from its twins by one return's last bit stops the run (stop rule 5)
    real_hold = R._hold_run

    def nudged(*args, **kwargs):
        res, measures = real_hold(*args, **kwargs)
        ret = res["ret"].to_numpy(dtype=float).copy()
        ret[-1] = float(np.nextafter(ret[-1], 1.0))
        res["ret"] = ret
        return res, measures

    monkeypatch.setattr(R, "_hold_run", nudged)
    monkeypatch.setattr(DB, "check_twin", real)
    out = tmp_path / "b"
    assert R.main(dry(out)) == 3
    assert "a twin of a run with no order differs from hold in ret" in _stopped(out)["status"]


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
    assert summary["grid"]["stage1"] == {"blocks": 1, "blocks_logged": 1, "runs_logged": 4}
    assert summary["grid"]["stage2"] == {"blocks": 2, "blocks_logged": 1, "runs_logged": 4}
    assert len(pd.read_parquet(out / "run0" / "runs.parquet")) == 4


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
    """The --fast dry run (decision-capable) on 2 workers, seed 1 (it has a default), with the boom checks allowed
    down to 1 window (the fast grid has 3 Kraken windows)."""
    root = tmp_path_factory.mktemp("decided")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(R, "TIMING_REPS_FAST", 1)
        mp.setattr(DB, "BOOM_MIN_WINDOWS", 1)
        assert R.main(dry(root / "w2", workers=2, seed=DECIDED_SEED)) == 0
    return root


def _load(root: Path) -> dict:
    return {
        "runs": pd.read_parquet(root / "run0" / "runs.parquet"),
        "ladders": pd.read_parquet(root / "run0" / "ladders.parquet"),
        "decision": read_json(root / "tracked" / "decision.json"),
        "csv": pd.read_csv(root / "tracked" / "runs.csv"),
        "start": read_json(root / "run0" / "start.json"),
        "summary": read_json(root / "run0" / "summary.json"),
    }


def test_workers_1_and_2_give_the_same_outputs_byte_for_byte(decided, tmp_path, monkeypatch):
    monkeypatch.setattr(DB, "BOOM_MIN_WINDOWS", 1)
    w1 = tmp_path / "w1"
    assert R.main(dry(w1, workers=1, seed=DECIDED_SEED)) == 0
    for name in ("runs.csv", "decision.json"):
        assert (decided / "w2" / "tracked" / name).read_bytes() == (w1 / "tracked" / name).read_bytes(), name
    for name in ("runs", "ladders"):
        a, b = (pd.read_parquet(root / "run0" / f"{name}.parquet") for root in (decided / "w2", w1))
        pd.testing.assert_frame_equal(a, b)
    assert (decided / "w2" / "run0" / "decision.json").read_bytes() == (
        decided / "w2" / "tracked" / "decision.json"
    ).read_bytes()


def _grid_ids(grid) -> set[str]:
    """Every run id the grid must log, from the plan's rules (section 7), not from run.py's loops."""
    ids = set()
    pools = [(1, "KRAKEN", "1x"), (2, "BINANCE", "1x"), (2, "KRAKEN", "2x")]
    for stage, source, cost in pools:
        for k in grid.windows[source]:
            for s0, f in grid.starts:
                ids.add(f"{stage}:{source}:{cost}:{k}:{s0:g}:{f:g}:hold:-:-:-:-")
                for y, z, x, m in grid.settings:
                    for kind in ("dip", "dca", "lump"):
                        ids.add(f"{stage}:{source}:{cost}:{k}:{s0:g}:{f:g}:{kind}:{y:g}:{z:g}:{x:g}:{m:g}")
    return ids


def test_every_run_is_logged_and_every_9th_run_is_rerun_from_scratch(decided):
    got = _load(decided / "w2")
    runs = got["runs"]
    assert set(runs["run_id"]) == _grid_ids(R.FAST) and len(runs) == len(_grid_ids(R.FAST)) == 208
    assert (runs["status"] == "ok").all()
    assert got["summary"]["counts"] == {"stage1": 78, "stage2": 130, "total": 208}
    assert got["decision"]["counts"]["stage1"] == {"got": 78, "expected": 78}
    loaded = panels(DECIDED_SEED)
    costs = {"1x": Costs.from_yaml(capital_usd=5000.0)}
    costs["2x"] = costs["1x"].stressed(2.0)
    windows = {s: {k: (a, z) for k, a, z in P.rolling_windows(s)} for s in H.SOURCES}

    def rerun(row):
        first, last = windows[row.source][row.window]
        piece = H.window_slice(loaded[row.source], first, last, missing=H.MISSING_CLOSES[row.source])
        assert (row.first_close, row.last_close, row.rows, row.year) == (first, last, len(piece), first.year)
        sig = DB.window_signal(DB.dip_signal(loaded[row.source], row.f), piece.index)
        p = {"kind": row.kind, "s0": row.s0, "f": row.f, **LIM}
        if row.kind == "dip":
            p.update(Y=row.Y, Z=row.Z, X=row.X, M=row.M)
        if row.kind in ("dca", "lump"):
            dip = runs[runs["run_id"] == row.run_id.replace(f":{row.kind}:", ":dip:")].iloc[0]
            p["total"] = dip["ordered_usd"]
        res = DB.dip_buy(p, piece, costs[row.cost], sig if row.kind == "dip" else None)
        return res, DB.run_measures(res, costs[row.cost], sig if row.kind == "dip" else None)

    for i, row in enumerate(runs.itertuples(index=False)):
        if i % 9:
            continue
        res, m = rerun(row)
        for key in DB.RUN_MEASURES:
            a, b = getattr(row, key), m[key]
            assert a == b or (isinstance(a, float) and math.isnan(a) and math.isnan(b)), (row.run_id, key)
        if row.kind == "dip":
            assert row.events_hash == DB.events_hash(res) and row.orders_hash == DB.orders_hash(res)
            twins = {}
            for kind in ("dca", "lump", "hold"):
                rid = row.run_id.replace(":dip:", f":{kind}:")
                if kind == "hold":
                    rid = ":".join(rid.split(":")[:7]) + ":-:-:-:-"
                twins[kind] = runs[runs["run_id"] == rid].iloc[0]
            assert row.T_dca == m["v_end"] / twins["dca"]["v_end"] - 1.0
            assert row.T_lump == m["v_end"] / twins["lump"]["v_end"] - 1.0
            assert row.T_hold == m["v_end"] / twins["hold"]["v_end"] - 1.0
            g = (m["v_end"] - twins["dca"]["v_end"]) / m["ordered_usd"] if m["ordered_usd"] > 0 else math.nan
            assert row.G == g or (math.isnan(row.G) and math.isnan(g))


def test_runs_csv_has_one_row_per_run_and_no_sharpe_or_value_column(decided):
    got = _load(decided / "w2")
    csv, runs = got["csv"], got["runs"]
    assert list(csv.columns) == list(R.CSV_COLUMNS) and len(csv) == len(runs) == 208
    assert not set(R.FORBIDDEN_CSV) & set(csv.columns) and "sharpe" not in " ".join(csv.columns).lower()
    assert csv["run_id"].tolist() == runs["run_id"].tolist()
    for col in ("F", "delta", "G", "T_dca", "T_lump", "T_hold", "orders"):
        np.testing.assert_allclose(csv[col].to_numpy(dtype=float), runs[col].to_numpy(dtype=float), rtol=1e-5)


def _my_d1(pool: pd.DataFrame):
    """Section 9's D1 written out here from the runs table, independently of dipbuy.d1."""
    if (pool["status"] != "ok").any():
        return "MISSING", {}
    dips, dcas = pool[pool["kind"] == "dip"], pool[pool["kind"] == "dca"]
    n = dips["window"].nunique()
    settings = sorted({(r.Y, r.Z, r.X, r.M) for r in dips.itertuples()})
    starts = sorted({(r.s0, r.f) for r in dips.itertuples()})
    usable, med = [], {}
    for s in settings:
        ok = True
        mine = dips[(dips["Y"] == s[0]) & (dips["Z"] == s[1]) & (dips["X"] == s[2]) & (dips["M"] == s[3])]
        for s0, f in starts:
            d = mine[(mine["s0"] == s0) & (mine["f"] == f)]
            c = dcas[(dcas["Y"] == s[0]) & (dcas["Z"] == s[1]) & (dcas["X"] == s[2]) & (dcas["M"] == s[3])]
            c = c[(c["s0"] == s0) & (c["f"] == f)]
            active = (d["orders"] >= 1).sum() * 2 >= n
            q_ok = np.percentile(d["F"], 90) <= np.percentile(c["F"], 90) and d["F"].max() <= c["F"].max()
            ok = ok and active and q_ok
        g = mine[mine["orders"] >= 1]["G"].to_numpy(dtype=float)
        # G~ is null in decision.json when no run of the setting has an order
        med[s] = (float(np.median(g)) if len(g) else None, float(np.median(mine["delta"])))
        if ok:
            usable.append(s)
    if not usable:
        return "NO DEFAULT", med
    top = max(med[s][0] for s in usable)
    cands = [s for s in usable if med[s][0] >= top - 1e-12]
    return list(max(cands, key=lambda s: (med[s][1], s[0], s[1], s[2], -s[3]))), med


def _my_d1_rows(pool: pd.DataFrame) -> dict:
    """D1's numbers per (setting, start), written out here: the windows with a ladder order, Q and Q_dca (linear
    90th percentiles) and the worst F of the dip runs and of their dca twins."""
    dips, dcas = pool[pool["kind"] == "dip"], pool[pool["kind"] == "dca"]
    out = {}
    for r in dips.drop_duplicates(["Y", "Z", "X", "M", "s0", "f"]).itertuples():
        at = (r.Y, r.Z, r.X, r.M, r.s0, r.f)
        keys = ("Y", "Z", "X", "M", "s0", "f")
        d = dips[np.logical_and.reduce([dips[k] == v for k, v in zip(keys, at, strict=True)])]
        c = dcas[np.logical_and.reduce([dcas[k] == v for k, v in zip(keys, at, strict=True)])]
        out[at] = (
            int((d["orders"] >= 1).sum()),
            float(np.percentile(d["F"], 90)),
            float(np.percentile(c["F"], 90)),
            float(d["F"].max()),
            float(c["F"].max()),
        )
    return out


def _their_d1(d1: dict) -> tuple[dict, dict]:
    """A decision.json D1 block's per-setting (G~, median delta) and per-(setting, start) numbers."""
    settings = {(s["Y"], s["Z"], s["X"], s["M"]): (s["G_med"], s["delta_med"]) for s in d1["settings"]}
    rows = {
        (r["Y"], r["Z"], r["X"], r["M"], r["s0"], r["f"]): (
            r["active_windows"],
            r["Q"],
            r["Q_dca"],
            r["worst_F"],
            r["worst_F_dca"],
        )
        for r in d1["table"]
    }
    return settings, rows


def test_the_decisions_are_recomputed_from_the_runs_table(decided):
    """D1 on every pool and boom removal, D2's label and D3 at the default by an independent statement of section 9;
    the boom years and windows; the 1x/2x check; the per-setting tables."""
    got = _load(decided / "w2")
    runs, ladders, decision = got["runs"], got["ladders"], got["decision"]
    k1 = runs[(runs["source"] == "KRAKEN") & (runs["cost"] == "1x")]
    want, med = _my_d1(k1)
    d1 = decision["stage1"]["D1"]
    assert d1["default"] == want and want != "NO DEFAULT"  # seed 1 has a default
    assert _their_d1(d1) == (med, _my_d1_rows(k1))
    returns = {int(k): v for k, v in got["start"]["year_returns"].items()}
    removals = P.boom_removals(returns)
    checks = decision["stage2"]["checks"]
    pools = {"Binance": runs[(runs["source"] == "BINANCE") & (runs["cost"] == "1x")]}
    pools["2x costs"] = runs[(runs["source"] == "KRAKEN") & (runs["cost"] == "2x")]
    for removal in removals:
        kept = [k for k in (0, 24, 48) if not any(P.overlaps(k, y) for y in removal["years"])]
        assert checks["boom"][removal["name"]] == {"years": removal["years"], "windows": kept}
        pools[removal["name"]] = k1[k1["window"].isin(kept)]
    moved, missing = [], []
    for name, p in pools.items():
        theirs = checks["D1"][name]["default"] if checks["D1"][name] is not None else "MISSING"
        if p.empty:
            assert checks["D1"][name] is None
            missing.append(name)
            continue
        mine, mine_med = _my_d1(p)
        assert theirs == mine, name
        # every number of the check, not only its default: the 1x and 2x pools can share a default (#74)
        assert _their_d1(checks["D1"][name]) == (mine_med, _my_d1_rows(p)), name
        if mine != want:
            moved.append(name)
    order = [r["name"] for r in removals] + [
        "Binance",
        "2x costs",
    ]  # run.py's order (decision.json sorts keys)
    label = decision["stage2"]["D2"]["label"]
    if moved:
        names = [n for n in order if n in moved] + [f"{n}: MISSING" for n in order if n in missing]
        assert label == f"NOT ROBUST ({', '.join(names)})"
    else:
        assert label == (
            "ROBUST" if not missing else f"MISSING ({', '.join(n for n in order if n in missing)})"
        )
    assert decision["headline"] == {"default": want, "label": label}
    # D3 at the default
    d3 = decision["stage2"]["D3"]
    at = k1[(k1["Y"] == want[0]) & (k1["Z"] == want[1]) & (k1["X"] == want[2]) & (k1["M"] == want[3])]
    for entry in d3["per_start"]:
        d = at[(at["kind"] == "dip") & (at["s0"] == entry["s0"]) & (at["f"] == entry["f"])]
        g = d[d["orders"] >= 1]["G"].to_numpy()
        assert entry["G"]["median"] == float(np.median(g)) and entry["G"]["p90"] == float(
            np.percentile(g, 90)
        )
        assert entry["T_dca"]["share_above_0"] == float((d["T_dca"] > 0).mean())
        assert entry["T_lump"]["p10"] == float(np.percentile(d["T_lump"], 10))
        assert entry["Q"] == float(np.percentile(d["F"], 90))
        for kind in ("dca", "lump"):
            t = at[(at["kind"] == kind) & (at["s0"] == entry["s0"]) & (at["f"] == entry["f"])]
            assert entry[f"Q_{kind}"] == float(np.percentile(t["F"], 90))
        hold = k1[(k1["kind"] == "hold") & (k1["s0"] == entry["s0"]) & (k1["f"] == entry["f"])]
        assert entry["Q_hold"] == float(np.percentile(hold["F"], 90))
        knife = ladders[ladders["run_id"].isin(d["run_id"])]["knife"].dropna().to_numpy()
        assert entry["knife_worst"] == (float(knife.max()) if len(knife) else None)
        assert entry["delta_median"] == float(np.median(d["delta"]))
        years = sorted({ts.year for ts in d["first_close"]})
        assert sorted(int(y) for y in entry["by_year"]) == years
    assert d3["budget"] == decision["budget"] == pf.risk_limits("steady")["max_drawdown_budget"]
    # the 1x/2x check and the tables
    k2 = pools["2x costs"]
    pairs = len(k1[k1["kind"] == "dip"])
    assert decision["cost_check"]["pairs"] == pairs == len(k2[k2["kind"] == "dip"])
    one = k1[k1["kind"] == "dip"].sort_values("run_id")["events_hash"].tolist()
    two = k2[k2["kind"] == "dip"].sort_values("run_id")["events_hash"].tolist()
    assert one == two
    a = k1[k1["kind"] == "dip"].set_index(["window", "s0", "f", "Y", "Z", "X", "M"])["orders_hash"]
    b = k2[k2["kind"] == "dip"].set_index(["window", "s0", "f", "Y", "Z", "X", "M"])["orders_hash"]
    assert decision["cost_check"]["orders_differ_1x_2x"] == int((a.sort_index() != b.sort_index()).sum())
    table = decision["stage2"]["tables"]["KRAKEN 1x"]
    assert len(table) == len(R.FAST.settings) * len(R.FAST.starts)
    row = table[0]
    d = k1[(k1["kind"] == "dip") & (k1["Y"] == row["Y"]) & (k1["Z"] == row["Z"]) & (k1["X"] == row["X"])]
    d = d[(d["M"] == row["M"]) & (d["s0"] == row["s0"]) & (d["f"] == row["f"])]
    assert row["T_hold_med"] == float(np.median(d["T_hold"])) and row["runs"] == 3


def test_every_pool_s_setting_table_is_recomputed(decided):
    """Section 14's full table per setting and start, for each of the three pools, from that pool's own dip rows
    (in the decided run the pools' rows differ: row 0's T_hold_med is 0.80 on Binance, 0.99 on Kraken 1x; #74)."""
    got = _load(decided / "w2")
    runs, tables = got["runs"], got["decision"]["stage2"]["tables"]
    pools = {"KRAKEN 1x": ("KRAKEN", "1x"), "BINANCE 1x": ("BINANCE", "1x"), "KRAKEN 2x": ("KRAKEN", "2x")}
    assert sorted(tables) == sorted(pools)
    for name, (source, cost) in pools.items():
        p = runs[(runs["source"] == source) & (runs["cost"] == cost) & (runs["kind"] == "dip")]
        assert len(tables[name]) == len(R.FAST.settings) * len(R.FAST.starts)
        for row in tables[name]:
            at = [p[k] == row[k] for k in ("Y", "Z", "X", "M", "s0", "f")]
            d = p[np.logical_and.reduce(at)]
            g = d[d["orders"] >= 1]["G"].to_numpy()
            assert row["runs"] == len(d) == len(R.FAST.windows[source]) and row["failed"] == 0, name
            assert row["active_share"] == float((d["orders"] >= 1).mean()), name
            assert row["G_med"] == (float(np.median(g)) if len(g) else None), name
            for k in ("T_dca", "T_lump", "T_hold", "delta", "usdc_left", "fees_pct_per_year"):
                assert row[f"{k}_med"] == float(np.median(d[k])), (name, k)
            assert row["orders_med"] == float(np.median(d["orders"])), name
            assert row["ladders_med"] == float(np.median(d["ladders"])), name
            knife = d["knife_worst"].dropna().to_numpy()
            assert row["knife_worst"] == (float(knife.max()) if len(knife) else None), name


def test_cost_check_counts_the_pairs_whose_orders_differ():
    """Section 10's 1x/2x check by hand: the Kraken dip pairs, the stop on moved events, and the sent orders that
    differ counted as a description (#74)."""
    runs = make_pool(windows=range(3))
    runs = runs[runs["kind"] == "dip"].copy()
    runs["events_hash"], runs["orders_hash"] = "e", "o"
    two = runs.copy()
    two["cost"] = "2x"
    two.loc[two.index[:2], "orders_hash"] = "x"
    binance = runs.copy()
    binance["source"] = "BINANCE"
    binance["orders_hash"] = "y"  # Binance is never paired
    got = R.cost_check(pd.concat([runs, two, binance], ignore_index=True))
    assert got == {"pairs": 3, "events_equal": 3, "orders_differ_1x_2x": 2}
    two.loc[two.index[2], "events_hash"] = "moved"
    with pytest.raises(R.Stop, match="1 Kraken dip runs' triggers, crossings or re-arms differ"):
        R.cost_check(pd.concat([runs, two], ignore_index=True))


def test_the_2x_check_is_its_own_pool_and_the_headline_and_d3_are_kraken_1x(decided, tmp_path, monkeypatch):
    """D2's '2x costs' check is D1 on the Kraken 2x pool, while the headline, D2's baseline and D3 stay on Kraken 1x.
    In the decided run both pools give the same default, so the 2x pool is made to rank another setting first: the
    headline's setting gets G = -1 in every Kraken 2x dip run (#74)."""
    monkeypatch.setattr(DB, "BOOM_MIN_WINDOWS", 1)
    head = tuple(_load(decided / "w2")["decision"]["stage1"]["D1"]["default"])
    real = R._block

    def sour(stage, source, cost, k):
        got = real(stage, source, cost, k)
        if cost == "2x":
            r = got["runs"]
            at = (r["kind"] == "dip") & np.logical_and.reduce(
                [r[key] == v for key, v in zip(DB.SETTING_KEYS, head, strict=True)]
            )
            assert at.any()
            r.loc[at, "G"] = -1.0
        return got

    monkeypatch.setattr(R, "_block", sour)
    assert R.main(dry(tmp_path / "a", seed=DECIDED_SEED)) == 0
    got = _load(tmp_path / "a")
    runs, dec = got["runs"], got["decision"]
    mine2, _ = _my_d1(runs[(runs["source"] == "KRAKEN") & (runs["cost"] == "2x")])
    assert tuple(mine2) != head  # another setting is usable on Kraken 2x
    assert tuple(dec["stage1"]["D1"]["default"]) == head
    assert dec["stage2"]["checks"]["D1"]["2x costs"]["default"] == mine2
    assert tuple(dec["headline"]["default"]) == head and tuple(dec["stage2"]["D2"]["default"]) == head
    assert dec["stage2"]["D2"]["checks"]["2x costs"] == mine2 and "2x costs" in dec["stage2"]["D2"]["label"]
    assert tuple(dec["stage2"]["D3"]["setting"][k] for k in DB.SETTING_KEYS) == head


def test_boom_checks_need_12_windows():
    """D2: a boom removal leaving fewer than 12 windows is MISSING (None), and exactly 12 is decided (#74). On
    windows 0 .. 23, without 2017 keeps windows 12 .. 23 (12); on 0 .. 22, 11; without 2017 and 2020, 1 or none."""
    assert DB.BOOM_MIN_WINDOWS == 12
    returns = {2017: 10.0, 2018: -0.7, 2019: 0.9, 2020: 3.0, 2021: 0.6, 2022: -0.6}
    for windows, kept in ((range(24), 12), (range(23), 11)):
        got = R.boom_checks(make_pool(windows=windows), returns)
        one, two = got["boom: without the best 1"], got["boom: without the best 2"]
        assert one["years"] == [2017] and one["windows"] == list(range(12, 12 + kept))
        assert (one["d1"] is not None) is (kept == 12) and two["d1"] is None
    decided_one = R.boom_checks(make_pool(windows=range(24)), returns)["boom: without the best 1"]["d1"]
    assert decided_one["windows"] == 12 and decided_one["default"] == (0.1, 0.1, 0.1, 0.25)


def test_the_unpatched_fast_run_reports_the_boom_checks_missing(tmp_path):
    """With the plan's minimum of 12 windows, the --fast grid's boom removals (3 Kraken windows) are MISSING in D1's
    checks and named so in D2's label (#74)."""
    assert R.main(dry(tmp_path / "a", seed=DECIDED_SEED)) == 0
    dec = read_json(tmp_path / "a" / "tracked" / "decision.json")
    for name in ("boom: without the best 1", "boom: without the best 2"):
        assert dec["stage2"]["checks"]["D1"][name] is None
        assert dec["stage2"]["D2"]["checks"][name] == DB.MISSING
        assert f"{name}: MISSING" in dec["stage2"]["D2"]["label"]


def test_the_ladders_table_and_every_twin_s_total(decided):
    got = _load(decided / "w2")
    runs, ladders = got["runs"], got["ladders"]
    dips = runs[runs["kind"] == "dip"]
    assert ladders["run_id"].isin(dips["run_id"]).all()
    assert (
        ladders.groupby("run_id").size().reindex(dips["run_id"], fill_value=0).tolist()
        == dips["ladders"].tolist()
    )
    for kind in ("dca", "lump"):
        twins = runs[runs["kind"] == kind].set_index(
            runs[runs["kind"] == kind]["run_id"].str.replace(kind, "dip")
        )
        joined = dips.set_index("run_id")["ordered_usd"]
        total = twins["ordered_usd"] + twins["unfilled_usd"]
        np.testing.assert_allclose(total.loc[joined.index].to_numpy(), joined.to_numpy(), rtol=1e-12)
    knife = ladders.groupby("run_id")["knife"].max().reindex(dips["run_id"])
    np.testing.assert_array_equal(knife.to_numpy(), dips["knife_worst"].to_numpy())
