"""The hold-mix-cap study script (``research/hold-mix-cap/run.py``) against PLAN.md sections 3-13 and the
``test_holdmix_run.py`` list of section 14: the start guards, the start record and RUNLOG line before any bar, the
data stops, every run logged, each consistency stop, and every reported number recomputed from its inputs.

SYNTHETIC data only: every run is a ``--synthetic`` dry run in ``tmp_path`` (``--fast``: section 14's small grid, or
a decision-capable small grid put in its place), the real catalog loader is replaced by one that fails the test if
it is ever reached (except where a test hands it synthetic bars on purpose), and the git state is injected where a
test needs one. Real-data guards run against stand-ins for every folder a real run uses (``real_folders``), so the
repo's recorded runs never decide which guard a test reaches (TESTING.md #48).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_portfolio import edit_steady_entry, set_steady_budget

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.panel import load_panel
from lab.runner import holdmix as H
from lab.runner import portfolio as pf
from lab.runner.reference import Costs
from lab.runner.steady import panel_hash

STUDY_DIR = Path(__file__).resolve().parents[1] / "research" / "hold-mix-cap"
NAME = "hold_mix_cap_run"
if NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(NAME, STUDY_DIR / "run.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[NAME] = _module
    _spec.loader.exec_module(_module)
R = sys.modules[NAME]

CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
SEED = 7
REF = (5000.0, "1x")
LIM = pf.risk_limits("steady")
TINY_TIMING = {
    "reps": 1,
    "cases": [],
    "seconds_per_run": {"365": 0.001, "2190": 0.002},
    "runs_365": 1,
    "runs_full": 1,
    "cpu_minutes": 1.0,
    "wall_minutes_on_2_workers": 0.5,
    "limit_cpu_minutes": 240.0,
    "python": "x",
}
# A grid the decision rules accept: the 6 bands, 7 caps, 3 wallet sizes and both cost levels, on one mix and two
# windows per source; full runs at 5,000 USD and 1x only (they feed the falls, never a rule), to keep it fast.
DECIDE = R.Grid(
    mixes=((0.5, 0.5),),
    bands=H.BANDS,
    caps=H.CAPS,
    books=H.BOOKS,
    costs=H.COST_LABELS,
    windows={"KRAKEN": (0, 59), "BINANCE": (8, 59)},
    full_settings=(REF,),
    name="test-decide",
)
# The smallest complete dry run, for tests about the guards and the bookkeeping rather than the grid
TINY = R.Grid(
    mixes=((0.5, 0.5),),
    bands=(0.2,),
    caps=(None, 2),
    books=(5000.0,),
    costs=H.COST_LABELS,
    windows={"KRAKEN": (0,), "BINANCE": (59,)},
    full=False,
    name="test-tiny",
)


def _refuse_real_bars(*args, **kwargs):
    raise AssertionError("a test reached the real catalog loader")


@pytest.fixture(autouse=True)
def no_real_bars(monkeypatch):
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)
    monkeypatch.setattr(R, "A0_REPS", 1)
    monkeypatch.setattr(R, "A0_REPS_FAST", 1)


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
    """Stand-ins for results/hold-mix-cap, data/catalog and this study's folder (the tracked RUNLOG and copies),
    so a real-data run can pass the path guard without touching the repo (#48)."""
    out, cat, here = tmp_path / "results" / "hold-mix-cap", tmp_path / "data" / "catalog", tmp_path / "here"
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


def edit_steady(cfg: Path, old: str, new: str) -> None:
    """Replace ``old`` (exactly once there) in the steady entry of ``cfg/risk_levels.yaml``, by key: never the
    first occurrence in the file, which is balanced's once Steady's budget is set (#55)."""
    edit_steady_entry(cfg, old, new)


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
        s: load_panel(s, "1d", last_close=R.LAST_CLOSE, catalog_dir="unused", loader=loader) for s in H.SOURCES
    }


# ------------------------------------------------------------------------------------- pinned values


def test_the_plan_s_counts_and_grids_are_pinned():
    total = R.expected_counts(R.PLAN_GRID)["total"]
    # section 11: 408,240 + 353,808 rolling, 13,608 x 2 full, 9,882 + 8,586 limit-only, 108,864 other
    assert total["grid_rolling"] == 408_240 + 353_808
    assert total["grid_full"] == 2 * 13_608
    assert total["limit_only"] == 9_882 + 8_586
    assert total["other"] == 108_864
    assert total["runs"] == 916_596
    assert (total["parity_band"], total["parity_limit"], total["parity"]) == (10_260, 3_078, 13_338)
    assert total["csv"] == 9_396 and total["lob"] == 6 * (9_882 + 8_586)
    assert total["runs_365"] + total["runs_full"] == 916_596 + 13_338
    per = R.expected_counts(R.PLAN_GRID)["per_source"]
    assert per["KRAKEN"]["csv"] == per["BINANCE"]["csv"] == 1134 + 2268 + 162 + 162 + 972
    g = R.PLAN_GRID
    assert g.mixes == H.MIXES and len(g.mixes) == 27 and g.bands == H.BANDS and g.caps == H.CAPS
    assert g.books == H.BOOKS and g.costs == H.COST_LABELS and g.full_resets == (None, 365)
    assert g.windows == {"KRAKEN": tuple(range(60)), "BINANCE": tuple(range(8, 60))}
    assert g.decidable and g.other_reading and g.full and g.full_settings is None
    f = R.FAST  # section 14: 3 mixes, 2 bands, 3 caps, 1 wallet size, both cost levels, 4 windows
    assert (len(f.mixes), len(f.bands), len(f.caps), len(f.books), f.costs) == (3, 2, 3, 1, ("1x", "2x"))
    assert all(len(f.windows[s]) == 4 for s in H.SOURCES) and not f.decidable
    fast = R.expected_counts(f)["total"]
    # by hand: per source 3 x 2 x 3 x 2 x 4 rolling, 3 x 2 x 3 x 2 x 2 full, 3 x 2 x 5 limit-only, 3 x 2 x 2 x 4 other
    assert (fast["grid_rolling"], fast["grid_full"], fast["limit_only"], fast["other"]) == (288, 144, 60, 96)
    assert (fast["parity_band"], fast["parity_limit"], fast["csv"]) == (60, 30, 2 * (3 * 2 * (4 + 7) + 12))
    assert R.ROWS == {"KRAKEN": 2190, "BINANCE": 1963} and R.LAST_CLOSE == pd.Timestamp("2023-01-01", tz="UTC")
    assert R.CPU_MINUTES_MAX == 240 and R.MAX_AMENDMENTS == 2 and R.A0_CASES == (
        (0.5, 0.5, 0.20, 15, None),
        (0.78, 0.5, 0.05, 1, None),
        (0.2, 0.0, 0.50, 120, 365),
    )


def test_the_hashed_files_are_section_12_s_and_the_config_hash_moves_with_them(tmp_path):
    paths = R.frozen_paths()
    validation = sorted(p.relative_to(R.REPO).as_posix() for p in (R.REPO / "lab" / "validation").glob("*.py"))
    assert paths == sorted(
        [
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
            "config/costs.yaml",
            "config/splits.yaml",
            "config/risk_levels.yaml",
            "pyproject.toml",
            "uv.lock",
            *validation,
        ]
    )
    hashes = R.file_hashes()
    assert hashes["research/hold-mix-cap/run.py"] == hashlib.sha256((STUDY_DIR / "run.py").read_bytes()).hexdigest()
    base = R.config_hash(hashes)
    assert R.config_hash(dict(reversed(list(hashes.items())))) == base
    moved = dict(hashes, **{"lab/runner/holdmix.py": "0" * 64})
    assert R.config_hash(moved) != base
    cfg = copy_config(tmp_path / "cfg")
    assert R.file_hashes(cfg) == hashes
    set_steady_budget(cfg, "TBD")  # a budget-only change from TBD to 30, set up whatever the real file holds (#55)
    tbd = R.file_hashes(cfg)
    edit_steady(cfg, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    other = R.file_hashes(cfg)
    assert [k for k in tbd if tbd[k] != other[k]] == ["config/risk_levels.yaml"]
    assert [k for k in hashes if hashes[k] != tbd[k]] in ([], ["config/risk_levels.yaml"])
    pinned = R.pinned_values()
    assert pinned["thresholds"] == {
        "EXTRA_OUT_MEDIAN": 7.0,
        "EXTRA_OUT_P90": 30.0,
        "RATE_MAX": 1.0,
        "FEE_MAX": 0.25,
        "CLOSE_SHARE": 0.9,
        "VALUE_FACTOR": 2.0,
    }
    assert pinned["headroom"] == 0.02 and len(pinned["windows"]["KRAKEN"]) == 60
    assert pinned["bars_sha256"] == R.BARS_SHA256 and pinned["panel_hashes"] == R.PANEL_HASHES


def test_amendment_rows_are_read_from_section_13_s_list_only():
    plan = "x\n**Amendments.**\n- **A0, ...**\n- **Amendment run 1 (2026-12-01): a bug**\n**Deviations.** y\n"
    assert R.amendment_row_present(plan, 1) and not R.amendment_row_present(plan, 2)
    assert not R.amendment_row_present(plan.replace("**Deviations.**", "Deviations"), 1)
    outside = "- **Amendment run 1** early\n**Amendments.**\n- **A0**\n**Deviations.**\n"
    assert not R.amendment_row_present(outside, 1)
    assert not R.amendment_row_present("**Deviations.**\n**Amendments.**\n- **Amendment run 1**\n", 1)
    assert not R.amendment_row_present(plan.replace("run 1 ", "run 10 "), 1)


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


def test_the_metric_keys_are_holdmix_s():
    panel = panels()["KRAKEN"].iloc[:60]
    costs = Costs.from_yaml(capital_usd=5000.0)
    p = R.hold_params((0.25, 0.25), 0.05, 4, None, LIM, first_buy_waits=False)
    res = H.hold_mix(p, panel, costs)
    pm = H.path_metrics(res, targets=(0.25, 0.25), band=0.05, min_cash=LIM["min_cash"], max_coin=LIM["max_coin"], wait=4)
    assert tuple(pm) == R.PATH_KEYS
    assert tuple(H.trade_sizes(res)) == R.SIZE_KEYS
    assert tuple(H.money_metrics(res, costs)) == R.MONEY_KEYS
    assert set(R.BAND_KEYS) <= set(R.PATH_KEYS) and set(R.CMP_METRICS) <= set(R.METRIC_KEYS)


def test_runs_csv_columns_are_pinned_and_hold_no_return_sharpe_or_fall():
    cols = R.CSV_COLUMNS
    assert cols[:15] == (*R.CSV_KEYS, "n_windows", "n_failed") and cols[0] == "label"
    assert len(cols) == 15 + 3 * len(R.ONCE_METRICS) + 3 * len(R.SETTING_METRICS) * 6
    assert len(set(cols)) == len(cols)
    for bad in R.FORBIDDEN_CSV:
        assert not any(bad in c for c in cols), bad
    assert "fees_pct_per_year_500_1x_tail" in cols and "min_leg_usd_50000_2x_worst" in cols
    assert R.SMALLER_WORSE == {"in_band_share", "min_leg_usd", "first_min_leg_usd"}


def test_jsonable_and_the_parity_comparison_by_hand():
    assert R.jsonable({1.5: [np.float64("nan"), np.int64(3), pd.NaT, pd.Timestamp("2020-01-01", tz="UTC")]}) == {
        "1.5": [None, 3, None, "2020-01-01T00:00:00+00:00"]
    }
    assert R.jsonable((np.bool_(True), np.array([1.0, math.inf]), np.datetime64("NaT", "us"))) == [True, [1.0, None], None]
    panel = panels()["KRAKEN"].iloc[:40]
    p = R.hold_params((0.25, 0.25), 0.05, 1, None, LIM, first_buy_waits=False)
    a = H.hold_mix(p, panel, Costs.from_yaml(capital_usd=5000.0))
    b = H.hold_mix(p, panel, Costs.from_yaml(capital_usd=5000.0))
    assert R.same_result(a, b)
    c = b.copy()
    c.attrs = dict(b.attrs)
    c.iloc[-1, c.columns.get_loc("ret")] = np.nextafter(c["ret"].iloc[-1], 1.0)
    assert not R.same_result(a, c)
    for key, value in (("orders", b.attrs["orders"][:-1]), ("n_trades", -1), ("snapshot_id", "x")):
        d = b.copy()
        d.attrs = {**b.attrs, key: value}
        assert not R.same_result(a, d), key
    e = b.copy()
    e.attrs = {**b.attrs, "fills": b.attrs["fills"].iloc[:-1]}
    assert not R.same_result(a, e)
    assert not R.same_result(a, b[list(b.columns)[::-1]])
    assert R.same_result(ValueError("x"), ValueError("x")) and not R.same_result(ValueError("x"), ValueError("y"))
    assert not R.same_result(ValueError("x"), b) and not R.same_result(RuntimeError("x"), RuntimeError("x"))


def test_rows_sort_by_the_pinned_key_and_run_ids_are_unique():
    rows = pd.DataFrame(
        {
            "i": range(6),
            "source": ["BINANCE", "KRAKEN", "KRAKEN", "KRAKEN", "KRAKEN", "KRAKEN"],
            "cap": ["none", "0.25", "none", "8", "none", "none"],
            "b": [0.1, 0.1, math.nan, 0.1, 0.1, 0.1],
            "R": [math.nan, math.nan, math.nan, math.nan, 365.0, math.nan],
        }
    )
    # Kraken first; band 0.1 before none; caps none, 8, 0.25; no reset before 365
    assert R.sort_rows(rows, ("source", "b", "cap", "R"))["i"].tolist() == [5, 4, 3, 1, 2, 0]
    assert R.run_id("KRAKEN", "rolling", 3, "grid", "lab", 0.5, 0.25, 0.05, "0.5", None, 500.0, "2x") == (
        "KRAKEN:rolling:3:grid:lab:0.5:0.25:0.05:0.5:-:500:2x"
    )
    assert R.run_id("BINANCE", "full", -1, "limit-only", "lab", 0.78, 0.5, None, "none", 365, 50000.0, "1x") == (
        "BINANCE:full:-1:limit-only:lab:0.78:0.5:-:none:365:50000:1x"
    )
    assert R.tasks(R.FAST) == [
        *(("KRAKEN", "rolling", k) for k in (0, 12, 26, 59)),
        ("KRAKEN", "full", -1),
        *(("BINANCE", "rolling", k) for k in (8, 20, 47, 59)),
        ("BINANCE", "full", -1),
    ]


def test_the_synthetic_panels_have_the_plan_s_shape_and_pass_the_panel_checks():
    got = panels()
    k, b = got["KRAKEN"], got["BINANCE"]
    assert len(k) == 2190 and len(b) == 1963
    assert k.index[0] == pd.Timestamp("2017-01-02", tz="UTC") and b.index[0] == pd.Timestamp("2017-08-18", tz="UTC")
    assert k.index[-1] == b.index[-1] == R.LAST_CLOSE
    assert pd.Timestamp("2018-01-13", tz="UTC") not in k.index and pd.Timestamp("2018-01-13", tz="UTC") in b.index
    for source, panel in got.items():
        R.check_panel(source, panel, {"snapshot_id": "synthetic"}, True)
        record = R.panel_record(panel)
        assert record["rows"] == R.ROWS[source] and record["hash"] == panel_hash(panel)
        assert (record["first"], record["last"], record["snapshot_id"]) == (panel.index[0], R.LAST_CLOSE, "synthetic")
    assert R.panel_record(k)["missing"] == ["2018-01-13T00:00:00+00:00"] and R.panel_record(b)["missing"] == []
    with pytest.raises(R.Stop, match="panel hash"):
        R.check_panel("KRAKEN", k, {"snapshot_id": "synthetic"}, False)


def test_the_timing_projects_the_plan_s_grid_by_hand():
    t = R.measure_throughput(LIM, None, 1)
    assert t["reps"] == 1 and len(t["cases"]) == 6
    assert [c["rows"] for c in t["cases"]] == [365, 2190] * 3
    per = {rows: max(c["backtest_ms"] + c["metrics_ms"] for c in t["cases"] if c["rows"] == rows) / 1e3 for rows in (365, 2190)}
    n = R.expected_counts(R.PLAN_GRID)["total"]
    assert t["runs_365"] == n["runs_365"] and t["runs_full"] == n["runs_full"]
    assert t["cpu_minutes"] == pytest.approx((n["runs_365"] * per[365] + n["runs_full"] * per[2190]) / 60, rel=1e-12)
    assert t["wall_minutes_on_2_workers"] == pytest.approx(t["cpu_minutes"] / 2, rel=1e-12)


def test_time_mode_writes_its_projection_to_a_scratch_folder_only(tmp_path):
    out = tmp_path / "timing"
    assert R.main(["--time", "--out-dir", str(out)]) == 0
    record = read_json(out / "timing.json")
    assert record["timing"]["limit_cpu_minutes"] == 240 and record["timing"]["reps"] == R.A0_REPS == 1
    assert record["label"] == R.LABEL and record["timing"]["runs_full"] == R.expected_counts(R.PLAN_GRID)["total"]["runs_full"]
    assert R.main(["--time", "--out-dir", str(R.REPO / "scratch-timing")]) == 2
    assert not (R.REPO / "scratch-timing").exists()
    assert R.main(["--time", "--synthetic", "1", "--out-dir", str(tmp_path / "t2")]) == 2
    assert not (tmp_path / "t2").exists()


# ----------------------------------------------------------------------------------------- start guards


def test_bad_flags_are_refused_before_anything_is_written(tmp_path, capsys):
    out = tmp_path / "out"
    assert R.main(["--fast", "--out-dir", str(out)]) == 2
    assert "--fast is for synthetic dry runs only" in capsys.readouterr().err
    assert R.main(dry(out, "--amendment", "0")) == 2
    assert R.main(dry(out, workers=0)) == 2
    assert not out.exists()


def test_a_dry_run_never_writes_into_the_study_folder_or_the_repo(tmp_path, capsys, tiny):
    before = tree(STUDY_DIR)
    results = R.REPO / "results" / "hold-mix-cap"
    existed = results.exists()
    for bad in (results, results / "dry", STUDY_DIR / "dry", R.REPO / "dry-run"):
        assert R.main(dry(bad)) == 2
        assert "never writes into" in capsys.readouterr().err
        assert not bad.exists() or bad == results and existed
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    assert tree(STUDY_DIR) == before and results.exists() == existed
    assert sorted(p.name for p in out.iterdir()) == ["run0", "tracked"]
    assert sorted(p.name for p in (out / "tracked").iterdir()) == ["RUNLOG.jsonl", "decision.json", "falls.csv", "runs.csv"]
    assert sorted(p.name for p in (out / "run0").iterdir()) == [
        "blocks",
        "decision.json",
        "failures.parquet",
        "limit_only_bands.parquet",
        "parity.parquet",
        "runs.parquet",
        "start.json",
        "summary.json",
    ]


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
    # the pinned folders pass the path guard and reach the next one (here: the bars hash)
    assert R.main(real_args(out, cat)) == 2
    assert "bars hash" in capsys.readouterr().err and not out.exists() and not here.exists()


def test_a_dirty_tree_is_refused_on_real_data_before_anything_is_written(tmp_path, monkeypatch, capsys, tiny):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(DIRTY))
    assert R.main(real_args(out, cat)) == 2
    err = capsys.readouterr().err
    assert "the git tree is dirty" in err and "stray.txt" in err
    assert not out.exists() and not here.exists()
    # a dry run on the same dirty tree runs (it records the state)
    assert R.main(dry(tmp_path / "dry")) == 0
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
    # a synthetic line for run 0 does not block a real run 0 (it reaches the bars-hash guard)
    (here / "RUNLOG.jsonl").write_text(json.dumps({"script": "run.py", "run": 0, "data": "synthetic"}) + "\n")
    assert R.main(real_args(out, cat)) == 2
    assert "bars hash" in capsys.readouterr().err
    assert not out.exists()


def test_the_amendment_rules(tmp_path, monkeypatch, capsys, tiny):
    monkeypatch.setattr(R, "PLAN_GRID", TINY)  # a broken guard below must not start the plan's 916,596 runs
    out = tmp_path / "dry"
    assert R.main(dry(out, "--amendment", "1")) == 2
    assert "run0" in capsys.readouterr().err and not out.exists()
    assert R.main(dry(out)) == 0
    assert R.main(dry(out)) == 2  # run 0 runs once
    assert "run 0 runs once" in capsys.readouterr().err
    for k in ("3", "-1"):
        assert R.main(dry(out, "--amendment", k)) == 2
        assert "numbered 1..2" in capsys.readouterr().err
    assert R.main(dry(out, "--amendment", "2")) == 2  # run1/start.json does not exist
    assert "run1" in capsys.readouterr().err
    assert R.main(dry(out, "--amendment", "1", fast=False)) == 2  # not the same kind of run
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
    assert R.main(dry(out, "--amendment", "1")) == 0
    start = read_json(out / "run1" / "start.json")
    assert start["run"] == 1 and start["fast"] is True
    assert [e["run"] for e in runlog(out / "tracked" / "RUNLOG.jsonl") if "event" not in e] == [0, 1]


def test_a_real_amendment_needs_its_plan_row(tmp_path, monkeypatch, capsys):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    (out / "run0").mkdir(parents=True)
    R.write_json(out / "run0" / "start.json", {"data": "real", "fast": False})
    plan = tmp_path / "PLAN.md"
    plan.write_text("**Amendments.**\n- **A0**\n**Deviations.**\n")
    monkeypatch.setattr(R, "PLAN", plan)
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(DIRTY))
    assert R.main(real_args(out, cat, "--amendment", "1")) == 2
    assert "lists no '- **Amendment run 1' row" in capsys.readouterr().err
    plan.write_text("**Amendments.**\n- **Amendment run 1 (2026-12-01)**: fix\n**Deviations.**\n")
    assert R.main(real_args(out, cat, "--amendment", "1")) == 2  # past the row guard: the dirty tree
    assert "the git tree is dirty" in capsys.readouterr().err
    assert not (out / "run1").exists() and not here.exists()


@pytest.mark.parametrize("key", ["min_cash_pct", "max_coin_pct"])
def test_a_steady_level_without_both_limits_is_refused(tmp_path, key, capsys):
    cfg = copy_config(tmp_path / "cfg")
    text = (cfg / "risk_levels.yaml").read_text()
    line = next(x for x in text.splitlines() if x.strip().startswith(key))
    edit_steady(cfg, line + "\n", "")
    out = tmp_path / "dry"
    assert R.main(dry(out, "--config-dir", str(cfg))) == 2
    assert "must set both min_cash_pct and max_coin_pct" in capsys.readouterr().err
    assert not out.exists()


def test_limits_that_refuse_a_mix_of_the_grid_stop_the_start(tmp_path, capsys):
    out = tmp_path / "dry"
    # each coin <= 52% with h: the plan's 52.5% coins refused, while the timing's cases and the --fast mixes pass
    cfg3 = copy_config(tmp_path / "cfg3")
    edit_steady(cfg3, "max_coin_pct: 60", "max_coin_pct: 54")
    assert R.main(dry(out, "--config-dir", str(cfg3))) == 2
    err = capsys.readouterr().err
    assert "refuse the grid" in err and "(0.7, 0.25)" in err and "(0.7, 0.75)" in err and not out.exists()
    cfg = copy_config(tmp_path / "cfg")
    edit_steady(cfg, "min_cash_pct: 20", "min_cash_pct: 30")  # cash >= 32% with h: s = 0.78 and 0.70 refused
    assert R.main(dry(out, "--config-dir", str(cfg))) == 2
    err = capsys.readouterr().err
    assert "refuse the grid" in err and "(0.78, 0.5)" in err and not out.exists()
    cfg2 = copy_config(tmp_path / "cfg2")
    edit_steady(cfg2, "coins: [BTC, ETH, USDC]", "coins: [BTC, USDC]")
    assert R.main(dry(out, "--config-dir", str(cfg2))) == 2
    assert "does not read" in capsys.readouterr().err


def test_the_catalog_snapshot_is_checked_before_any_bar(tmp_path, monkeypatch, clean_git, capsys):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    assert R.main(real_args(out, cat)) == 2
    assert "cannot read" in capsys.readouterr().err
    write_snapshot(cat, bars_hash="f" * 64)
    assert R.main(real_args(out, cat)) == 2
    assert "is not 08f5ca2c" in capsys.readouterr().err
    write_snapshot(cat, snapshot_id="")
    assert R.main(real_args(out, cat)) == 2
    assert "names no snapshot_id" in capsys.readouterr().err
    assert not out.exists() and not here.exists()


def test_a_projection_above_240_cpu_minutes_refuses_a_real_run_only(tmp_path, monkeypatch, clean_git, capsys, tiny):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    slow = dict(TINY_TIMING, cpu_minutes=240.5)
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(slow))
    assert R.main(real_args(out, cat)) == 2
    assert "stop rule 9" in capsys.readouterr().err and not out.exists() and not here.exists()
    dry_out = tmp_path / "dry"
    assert R.main(dry(dry_out)) == 0
    assert read_json(dry_out / "run0" / "start.json")["timing"]["cpu_minutes"] == 240.5
    # exactly 240 starts (it is then stopped by the stand-in bars' panel hash, after the start record)
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(slow, cpu_minutes=240.0))
    monkeypatch.setattr(catalog, "load_bars", R.synthetic_bar_loader(SEED))
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    assert R.main(real_args(out, cat)) == 3
    assert read_json(out / "run0" / "start.json")["timing"]["cpu_minutes"] == 240.0


def test_an_engine_that_fails_the_timing_refuses_the_start(tmp_path, monkeypatch, capsys):
    def broken(params, bars, costs=None):
        raise RuntimeError("engine broken")

    monkeypatch.setattr(H, "hold_mix", broken)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 2
    assert "the A0 re-timing failed (section 11): RuntimeError: engine broken" in capsys.readouterr().err
    assert not out.exists()


# ---------------------------------------------------------------------------- start record and the data


def test_the_start_record_and_the_runlog_line_exist_before_any_bar_is_read(tmp_path, monkeypatch, tiny):
    out = tmp_path / "dry"
    seen = []
    real_loader = R.synthetic_bar_loader

    def watching(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            start_json = out / "run0" / "start.json"
            seen.append((start_json.is_file(), len(runlog(out / "tracked" / "RUNLOG.jsonl"))))
            assert end == R.LAST_CLOSE  # load_panel asks for the train window only
            return inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)

        return loader

    monkeypatch.setattr(R, "synthetic_bar_loader", watching)
    assert R.main(dry(out)) == 0
    assert seen and all(s == (True, 1) for s in seen) and len(seen) == 4
    start = read_json(out / "run0" / "start.json")
    for key in ("utc", "git", "config_hash", "file_hashes", "risk_limits", "costs", "grid", "windows", "thresholds"):
        assert key in start
    assert start["risk_limits"]["min_cash"] == LIM["min_cash"] and start["risk_limits"]["sha256"] == LIM["sha256"]
    assert start["windows"]["KRAKEN"][0] == [0, "2017-01-02T00:00:00+00:00", "2018-01-01T00:00:00+00:00"]
    assert len(start["windows"]["BINANCE"]) == 52 and start["windows"]["BINANCE"][0][0] == 8
    assert start["costs"]["5000_2x"]["gas_usd_per_trade"] == 2 * start["costs"]["5000_1x"]["gas_usd_per_trade"]
    assert sorted(start["costs"]) == ["5000_1x", "5000_2x"]  # the --fast grid's one wallet size
    assert start["costs"]["5000_1x"]["capital_usd"] == 5000.0
    assert start["timing"]["reps"] == 1 and start["config_hash"] == R.config_hash(R.file_hashes())
    want = panels()
    for source in H.SOURCES:
        assert start["panels"][source]["rows"] == R.ROWS[source]
        assert start["panels"][source]["hash"] == panel_hash(want[source])
    line = runlog(out / "tracked" / "RUNLOG.jsonl")[0]
    assert {k: line[k] for k in ("script", "run", "data", "snapshot_id", "config_hash")} == {
        "script": "run.py",
        "run": 0,
        "data": "synthetic",
        "snapshot_id": "synthetic",
        "config_hash": start["config_hash"],
    }


def _leaky(close: str):
    """A synthetic loader that also returns one bar closing at ``close`` (after the last train close)."""
    real_loader = R.synthetic_bar_loader

    def factory(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            extra = bars.iloc[[-1]].copy()
            extra.index = pd.DatetimeIndex([pd.Timestamp(close, tz="UTC")], name="ts").as_unit("us")
            out = pd.concat([bars, extra])
            out.attrs = bars.attrs
            return out

        return loader

    return factory


@pytest.mark.parametrize("close", ["2023-01-02", "2024-07-02"])
def test_a_close_after_the_train_window_stops_the_run_before_any_backtest(tmp_path, monkeypatch, close):
    monkeypatch.setattr(R, "synthetic_bar_loader", _leaky(close))
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "3" and "report the incident" in summary["status"]
    assert close in summary["status"]
    events = [e for e in runlog(out / "tracked" / "RUNLOG.jsonl") if "event" in e]
    assert events == [{**events[0], "event": "stop rule 3"}]
    assert "panels" not in read_json(out / "run0" / "start.json")
    assert not (out / "run0" / "runs.parquet").exists() and not (out / "tracked" / "runs.csv").exists()


def _reshaped(change):
    real_loader = R.synthetic_bar_loader

    def factory(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            got = change(instrument, bars)
            got.attrs = bars.attrs
            return got

        return loader

    return factory


def test_a_wrong_row_count_stops_the_run(tmp_path, monkeypatch):
    day = pd.Timestamp("2020-06-01", tz="UTC")
    monkeypatch.setattr(R, "synthetic_bar_loader", _reshaped(lambda i, b: b.drop(day) if i.startswith("BTC") else b))
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "5" and "2189 rows, expected 2190" in summary["status"]
    recorded = read_json(out / "run0" / "start.json")["panels"]  # what was loaded is recorded before the checks
    assert recorded["KRAKEN"]["rows"] == 2189 and recorded["BINANCE"]["rows"] == 1962


def test_a_binance_panel_without_a_window_s_first_close_stops_the_run(tmp_path, monkeypatch):
    """2017-09-02 (window k = 8's first close) missing and 2017-08-17 added: still 1963 rows (section 6)."""
    gone, added = pd.Timestamp("2017-09-02", tz="UTC"), pd.Timestamp("2017-08-17", tz="UTC")

    def change(instrument, bars):
        if not instrument.endswith("BINANCE"):
            return bars
        extra = bars.iloc[[0]].copy()
        extra.index = pd.DatetimeIndex([added], name="ts").as_unit("us")
        return pd.concat([extra, bars.drop(gone)])

    monkeypatch.setattr(R, "synthetic_bar_loader", _reshaped(change))
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "5" and "BINANCE window 8:" in summary["status"] and "2017-09-02" in summary["status"]
    recorded = read_json(out / "run0" / "start.json")["panels"]["BINANCE"]
    assert recorded["rows"] == 1963 and recorded["first"] == "2017-08-17T00:00:00+00:00"


def test_real_data_with_other_bars_or_another_snapshot_stops_the_run(tmp_path, monkeypatch, clean_git):
    # the measured A0 speed must not decide which guard a real run reaches (under coverage it is ~4x slower): #51
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(TINY_TIMING))
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat, snapshot_id="1746a21b75683e76")
    synthetic = R.synthetic_bar_loader(SEED)
    monkeypatch.setattr(catalog, "load_bars", synthetic)  # stands in for the catalog on purpose
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    assert R.main(real_args(out, cat)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "5" and "panel hash" in summary["status"]
    want = panels()
    assert read_json(out / "run0" / "start.json")["panels"]["KRAKEN"]["hash"] == panel_hash(want["KRAKEN"])
    assert [e.get("event") for e in runlog(here / "RUNLOG.jsonl")] == [None, "stop rule 5"]
    assert runlog(here / "RUNLOG.jsonl")[0]["data"] == "real"
    shutil.rmtree(out)
    (here / "RUNLOG.jsonl").unlink()
    monkeypatch.setattr(R, "PANEL_HASHES", {s: panel_hash(want[s]) for s in H.SOURCES})
    assert R.main(real_args(out, cat)) == 3
    assert "panel snapshot 'synthetic' is not '1746a21b75683e76'" in read_json(out / "run0" / "summary.json")["status"]


# ------------------------------------------------------------------------------------ consistency stops


def _wrap_hold_mix(monkeypatch, change):
    """The grid's engine broken by ``change``; the A0 timing at start (which runs the same engine) is stubbed."""
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(TINY_TIMING))
    real = H.hold_mix

    def fake(params, bars, costs=None):
        res = real(params, bars, costs)
        changed = change(params, costs, res)
        return res if changed is None else changed

    monkeypatch.setattr(H, "hold_mix", fake)


def _logged_blocks(out: Path) -> list[Path]:
    folder = out / "run0" / "blocks"
    return sorted(folder.glob("*.runs.parquet")) if folder.is_dir() else []


def _stopped(out: Path, *, runs_logged: bool = False) -> dict:
    """A stop rule 8: recorded, and nothing reported (no runs.csv, no decision.json). What was computed stays in the
    run folder (stop rule 6, INTERPRETATIONS["logging"]): every block that returned, in run0/blocks/, and, when the
    stop came after the grid (``runs_logged``), the four tables in run0/."""
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "8", summary["status"]
    assert not (out / "tracked" / "runs.csv").exists() and not (out / "tracked" / "decision.json").exists()
    assert not (out / "run0" / "decision.json").exists()
    for name in ("runs", "limit_only_bands", "parity", "failures"):
        assert (out / "run0" / f"{name}.parquet").exists() is runs_logged, name
    blocks = _logged_blocks(out)
    assert len(blocks) == summary["grid"]["blocks_logged"]
    assert sum(len(pd.read_parquet(b)) for b in blocks) == summary["grid"]["runs_logged"]
    if runs_logged:
        assert len(pd.read_parquet(out / "run0" / "runs.parquet")) == summary["grid"]["runs_logged"]
    assert [e.get("event") for e in runlog(out / "tracked" / "RUNLOG.jsonl")] == [None, "stop rule 8"]
    return summary


def test_a_path_that_moves_with_the_cost_setting_stops_the_run(tmp_path, monkeypatch):
    def change(params, costs, res):
        if costs.pool_fee_bps > 5.0:  # the 2x setting
            col = res.columns.get_loc("w_BTC")
            res.iloc[-1, col] = np.nextafter(res.iloc[-1, col], 2.0)

    _wrap_hold_mix(monkeypatch, change)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "path hash differs between cost settings" in _stopped(out)["status"]


def test_a_wrong_in_wait_flag_stops_the_run(tmp_path, monkeypatch):
    def change(params, costs, res):
        if len(res.attrs["orders"]) > 1:
            flags = res.attrs["in_wait"].copy()
            flags[-1] = not flags[-1]
            res.attrs["in_wait"] = flags

    _wrap_hold_mix(monkeypatch, change)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "in-wait flag" in _stopped(out)["status"]


def test_the_other_reading_s_wait_is_checked_from_the_first_buy(tmp_path, monkeypatch):
    """An engine that ignores first_buy_waits sends some band order inside W days of the first buy: the other
    reading's check (path_metrics with first_buy_waits=True) must stop it."""
    real = H.hold_mix
    monkeypatch.setattr(H, "hold_mix", lambda p, bars, costs=None: real({**p, "first_buy_waits": False}, bars, costs))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    status = _stopped(out)["status"]
    assert ":other:" in status and ("comes less than" in status or "in-wait flag" in status)


def test_fees_that_differ_from_the_cost_column_stop_the_run(tmp_path, monkeypatch):
    def change(params, costs, res):
        bars = res.attrs["fills"]["bar"].to_numpy()
        later = bars[bars >= 2]
        if len(later):
            col = res.columns.get_loc("cost")
            res.iloc[int(later[0]), col] = res.iloc[int(later[0]), col] * (1 + 1e-9)

    _wrap_hold_mix(monkeypatch, change)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "differ from the cost column" in _stopped(out)["status"]


@pytest.mark.parametrize("kind", ["band", "limit-only"])
def test_a_failed_parity_check_stops_the_run(tmp_path, monkeypatch, kind):
    real = pf.rebalance

    def fake(params, bars, costs=None):
        res = real(params, bars, costs)
        if (params["band"] == 1.0) == (kind == "limit-only"):
            col = res.columns.get_loc("ret")
            res.iloc[-1, col] = np.nextafter(res.iloc[-1, col], 1.0)
        return res

    monkeypatch.setattr(pf, "rebalance", fake)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert f"parity ({kind}) fails" in _stopped(out)["status"]


def test_a_lost_run_stops_the_run_at_the_count(tmp_path, monkeypatch, tiny):
    real = R._block

    def lossy(source, scope, k):
        got = real(source, scope, k)
        if (source, scope) == ("BINANCE", "rolling"):
            got["runs"] = got["runs"].iloc[:-1]
        return got

    monkeypatch.setattr(R, "_block", lossy)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    status = _stopped(out, runs_logged=True)["status"]  # the rows that were computed are kept (stop rule 6)
    n = R.expected_counts(TINY)["total"]
    assert "counts differ" in status and f"'runs': ({n['runs'] - 1}, {n['runs']})" in status
    assert f"'limit_only': ({n['limit_only'] - 1}, {n['limit_only']})" in status


def test_a_hashed_file_that_changes_during_the_run_stops_it(tmp_path, monkeypatch, tiny):
    real = R.file_hashes
    calls = []

    def moving(config_dir=None):
        calls.append(1)
        got = real(config_dir)
        return got if len(calls) == 1 else {**got, "lab/runner/holdmix.py": "0" * 64}

    monkeypatch.setattr(R, "file_hashes", moving)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "10" and not (out / "tracked" / "runs.csv").exists()


def test_a_failed_run_is_logged_with_its_error_and_the_grid_goes_on(tmp_path, monkeypatch):
    def change(params, costs, res):
        if params["w_btc"] == 0.39 and params["band"] == 0.3 and params["wait_days"] == 15 and costs.pool_fee_bps > 5:
            raise ValueError("a synthetic refusal: the fill would cost the whole wallet")

    _wrap_hold_mix(monkeypatch, change)
    out = tmp_path / "dry"
    assert R.main(dry(out, workers=2)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    failed = runs[runs["status"] == "failed"]
    # per source: 4 rolling windows + 2 full runs (no reset, yearly reset), each at 5,000 USD 2x
    assert len(failed) == 12 and len(runs) == 588
    assert set(failed["error"]) == {"ValueError: a synthetic refusal: the fill would cost the whole wallet"}
    assert set(failed["cost"]) == {"2x"} and set(failed["s"]) == {0.78} and set(failed["cap"]) == {"2"}
    assert failed[list(R.METRIC_KEYS)].isna().all().all() and (failed["path_hash"] == "").all()
    assert failed["rows"].isin([364, 365, 366]).sum() == 8
    assert sorted(failed.loc[failed["scope"] == "full", "rows"]) == [1963, 1963, 2190, 2190]
    fails = pd.read_parquet(out / "run0" / "failures.parquet")
    assert sorted(fails["run_id"]) == sorted(failed["run_id"])
    assert all("a synthetic refusal" in t and "Traceback" in t for t in fails["traceback"])
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"] == "complete" and summary["failed_runs"] == 12
    csv = pd.read_csv(out / "tracked" / "runs.csv", dtype={"cap": str})
    hit = csv[(csv["s"] == 0.78) & (csv["b"] == 0.3) & (csv["cap"] == "2") & (csv["reading"] == "lab")]
    assert sorted(hit["n_failed"]) == [1, 1, 1, 1, 4, 4]
    assert hit.loc[hit["scope"] == "rolling", "fees_pct_per_year_5000_2x"].isna().all()
    assert hit.loc[hit["scope"] == "rolling", "fees_pct_per_year_5000_1x"].notna().all()
    decision = read_json(out / "tracked" / "decision.json")
    assert decision["failed_runs"] == 12 and decision["decidable"] is False and decision["rule_E"] is None


FAILING = R.Grid(
    mixes=((0.5, 0.5),),
    bands=H.BANDS,
    caps=H.CAPS,
    books=H.BOOKS,
    costs=H.COST_LABELS,
    windows={"KRAKEN": (0,), "BINANCE": (59,)},
    full=False,
    other_reading=False,
    name="test-failing",
)


def test_a_failed_run_makes_decision_json_missing_and_fills_rule_e(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "FAST", FAILING)
    kraken_0 = pd.Timestamp("2017-01-02", tz="UTC")

    def change(params, costs, res):
        if res.index[0] == kraken_0 and params["band"] == 0.2 and params["wait_days"] == 30:
            if costs.capital_usd == 5000.0 and costs.pool_fee_bps == 5.0:
                raise ValueError("a synthetic refusal")

    _wrap_hold_mix(monkeypatch, change)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    (failed,) = runs.loc[runs["status"] == "failed", "run_id"]
    assert failed == "KRAKEN:rolling:0:grid:lab:0.5:0.5:0.2:1:-:5000:1x"
    d = read_json(out / "tracked" / "decision.json")
    assert d["failed_runs"] == 1 and d["decidable"] is True
    assert d["sources"]["KRAKEN"]["N_star"]["0.2"] == H.MISSING and d["sources"]["BINANCE"]["N_star"]["0.2"] != H.MISSING
    assert d["sources"]["KRAKEN"]["rule_C"]["5000/1x"]["outcome"] == H.MISSING
    assert d["robust"]["label"] == H.MISSING and d["robust"]["headline"] == {"band": H.MISSING, "cap": H.MISSING}
    assert d["per_share"] is None and d["falls"]["rows"] == 0 and "MISSING" in d["falls"]["status"]
    assert d["descriptions"]["KRAKEN"]["years"]["0.2"] == H.MISSING
    assert (out / "tracked" / "falls.csv").read_text() == ",".join(H.FALLS_COLUMNS) + "\n"
    e = d["rule_E"]
    assert e["failed_runs"] == 1 and e["dropped_pairs"] == [["KRAKEN", "rolling", 0, 0.5, 0.5]]
    assert "cannot apply the rules" in e["error"]  # Kraken's only pair is dropped: its pool is empty
    # A5 on the MISSING headline: every removal leaves fewer than 12 windows on this grid, so it is MISSING too
    boom = d["boom_check"]
    assert len(boom["removals"]) == 8 and {r["status"] for r in boom["removals"]} == {H.MISSING}


def test_a_crash_while_writing_the_outputs_is_recorded(tmp_path, monkeypatch, tiny):
    def broken(results, g, run_dir):
        raise OSError("disk full")

    monkeypatch.setattr(R, "write_outputs", broken)
    out = tmp_path / "dry"
    with pytest.raises(OSError, match="disk full"):
        R.main(dry(out))
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"] == "crashed: OSError: disk full" and "Traceback" in summary["traceback"]
    assert [e.get("event") for e in runlog(out / "tracked" / "RUNLOG.jsonl")] == [None, "crashed"]


def test_a_fast_dry_run_computes_no_decision_and_writes_its_tables(tmp_path):
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    decision = read_json(out / "tracked" / "decision.json")
    assert decision["decidable"] is False and "--fast" in decision["reason"]
    assert decision["label"] == R.LABEL and decision["status"] == R.STATUS and decision["grid"] == "fast"
    assert decision["counts"]["got"]["runs"] == 588 and "robust" not in decision
    assert (out / "tracked" / "falls.csv").read_text() == ",".join(H.FALLS_COLUMNS) + "\n"
    assert (out / "run0" / "decision.json").read_bytes() == (out / "tracked" / "decision.json").read_bytes()
    csv = pd.read_csv(out / "tracked" / "runs.csv", dtype={"cap": str})
    assert list(csv.columns) == list(R.CSV_COLUMNS) and len(csv) == 156 and (csv["label"] == R.LABEL).all()
    parity = pd.read_parquet(out / "run0" / "parity.parquet")
    assert len(parity) == 90 and set(parity["outcome"]) == {"equal"}
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"] == "complete" and summary["headline"] is None
    assert [e.get("event") for e in runlog(out / "tracked" / "RUNLOG.jsonl")] == [None, "complete"]


# ------------------------------------------------------------- every reported number from its inputs


@pytest.fixture(scope="module")
def decided(tmp_path_factory):
    """A decision-capable dry run (the DECIDE grid in place of --fast) on 2 workers."""
    root = tmp_path_factory.mktemp("decided")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(R, "A0_REPS_FAST", 1)
        mp.setattr(R, "FAST", DECIDE)
        mp.setattr(R, "BOOM_MIN_WINDOWS", 1)  # DECIDE has 2 windows a source: let A5's removals compute
        assert R.main(dry(root / "w2", workers=2)) == 0
    return root


def _load(root: Path) -> dict:
    return {
        "runs": pd.read_parquet(root / "run0" / "runs.parquet"),
        "lob": pd.read_parquet(root / "run0" / "limit_only_bands.parquet"),
        "parity": pd.read_parquet(root / "run0" / "parity.parquet"),
        "decision": read_json(root / "tracked" / "decision.json"),
        "csv": pd.read_csv(root / "tracked" / "runs.csv", dtype={"cap": str}),
        "falls": pd.read_csv(root / "tracked" / "falls.csv", dtype={"cap": str, "grid_cap": str}),
        "start": read_json(root / "run0" / "start.json"),
    }


def test_workers_1_and_2_give_the_same_tables_byte_for_byte(decided, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "FAST", DECIDE)
    monkeypatch.setattr(R, "BOOM_MIN_WINDOWS", 1)
    w1 = tmp_path / "w1"
    assert R.main(dry(w1, workers=1)) == 0
    for name in ("runs.csv", "falls.csv", "decision.json"):
        assert (decided / "w2" / "tracked" / name).read_bytes() == (w1 / "tracked" / name).read_bytes(), name
    a, b = (pd.read_parquet(root / "run0" / "runs.parquet") for root in (decided / "w2", w1))
    pd.testing.assert_frame_equal(a, b)


def _grid_rows(grid) -> set[str]:
    """Every run id the grid must log, built from the plan's rules, not from run.py's loops."""
    ids = set()
    for source in H.SOURCES:
        for scope, windows in (("rolling", grid.windows[source]), ("full", (-1,))):
            settings = grid.settings if scope == "rolling" else grid.full_settings
            resets = (None,) if scope == "rolling" else (None, 365)
            for k in windows:
                for s, f in grid.mixes:
                    for b in grid.bands:
                        for cap in grid.caps:
                            for reset in resets:
                                for book, cost in settings:
                                    ids.add(R.run_id(source, scope, k, "grid", "lab", s, f, b, H.cap_label(cap), reset, book, cost))
                            if scope == "rolling" and cap is not None:
                                ids.add(R.run_id(source, scope, k, "grid", "other", s, f, b, H.cap_label(cap), None, *REF))
                    for book, cost in settings:
                        ids.add(R.run_id(source, scope, k, "limit-only", "lab", s, f, None, "none", None, book, cost))
    return ids


def test_every_run_is_logged_and_each_run_s_numbers_come_from_its_configuration(decided):
    t = _load(decided / "w2")
    runs, lob = t["runs"], t["lob"]
    assert set(runs["run_id"]) == _grid_rows(DECIDE) and len(runs) == len(set(runs["run_id"]))
    assert len(runs) == R.expected_counts(DECIDE)["total"]["runs"] == 1346 and (runs["status"] == "ok").all()
    assert (runs["snapshot_id"] == "synthetic").all() and (runs["commit"] == t["start"]["git"]["commit"]).all()
    assert len(lob) == 6 * (runs["comparator"] == "limit-only").sum()
    assert len(t["parity"]) == R.expected_counts(DECIDE)["total"]["parity"] and set(t["parity"]["outcome"]) == {"equal"}
    got = panels()
    windows = {s: dict((k, (a, z)) for k, a, z in H.rolling_windows(s)) for s in H.SOURCES}
    # recompute every 9th run from scratch with holdmix: params, wallet size, costs, reading, metric band
    for _, row in runs.iloc[::9].iterrows():
        first, last = H.full_window(row["source"]) if row["scope"] == "full" else windows[row["source"]][row["window"]]
        piece = H.window_slice(got[row["source"]], first, last, missing=H.MISSING_CLOSES[row["source"]])
        assert (row["first_close"], row["last_close"], row["rows"]) == (first, last, len(piece))
        costs = Costs.from_yaml(capital_usd=row["V"])
        costs = costs.stressed() if row["cost"] == "2x" else costs
        lo = row["comparator"] == "limit-only"
        band = H.LIMIT_ONLY_BAND if lo else row["b"]
        reset = None if math.isnan(row["R"]) else int(row["R"])
        other = row["reading"] == "other"
        p = R.hold_params((row["w_btc"], row["w_eth"]), band, row["W"], reset, LIM, first_buy_waits=other)
        assert (row["w_btc"], row["w_eth"]) == H.mix_targets(row["s"], row["f"])
        assert row["W"] == (1 if lo else H.wait_days(None if row["cap"] == "none" else float(row["cap"])))
        res = H.hold_mix(p, piece, costs)
        want = {
            **H.path_metrics(res, targets=(p["w_btc"], p["w_eth"]), band=band, min_cash=LIM["min_cash"], max_coin=LIM["max_coin"], wait=row["W"], first_buy_waits=other),
            **H.trade_sizes(res),
            **H.money_metrics(res, costs),
        }
        if lo:
            want.update(dict.fromkeys(R.BAND_KEYS, math.nan))
        for key, value in want.items():
            mine = row[key]
            assert (pd.isna(mine) and pd.isna(value)) or mine == value, (row["run_id"], key)
        assert row["path_hash"] == H.path_hash(res)
        if lo:  # its band rows
            for _, br in lob[lob["run_id"] == row["run_id"]].iterrows():
                pm = H.path_metrics(res, targets=(p["w_btc"], p["w_eth"]), band=br["b"], min_cash=LIM["min_cash"], max_coin=LIM["max_coin"], wait=1)
                assert all(br[k] == pm[k] for k in R.BAND_KEYS)
    # the comparisons (section 8), every grid row
    key = ["source", "scope", "window", "s", "f", "V", "cost"]
    index = {tuple(r[c] for c in [*key, "b"]) + (-1.0 if math.isnan(r["R"]) else r["R"],): r for _, r in runs[(runs["comparator"] == "grid") & (runs["reading"] == "lab") & (runs["cap"] == "none")].iterrows()}
    limit = {tuple(r[c] for c in key): r for _, r in runs[runs["comparator"] == "limit-only"].iterrows()}
    lob_d = {(r["run_id"], r["b"]): r["out_days_per_year"] for _, r in lob.iterrows()}
    for _, r in runs.iterrows():
        if r["comparator"] == "limit-only":
            assert all(pd.isna(r[f"vs_{w}_{m}"]) for w in ("nocap", "limit") for m in R.CMP_METRICS)
            continue
        ref = index[tuple(r[c] for c in [*key, "b"]) + (-1.0 if math.isnan(r["R"]) else r["R"],)]
        lim = limit[tuple(r[c] for c in key)]
        for m in R.CMP_METRICS:
            other = lob_d[(lim["run_id"], r["b"])] if m == "out_days_per_year" else lim[m]
            for name, want in ((f"vs_nocap_{m}", r[m] - ref[m]), (f"vs_limit_{m}", r[m] - other)):
                assert r[name] == want or (np.isnan(r[name]) and np.isnan(want)), (r["run_id"], name)


def _agg(values: pd.Series, metric: str) -> tuple[float, float, float]:
    x = values.to_numpy(dtype=float)
    x = x[~np.isnan(x)]
    if not len(x):
        return (math.nan,) * 3
    smaller = metric in R.SMALLER_WORSE
    return float(np.median(x)), float(np.percentile(x, 10 if smaller else 90)), float(x.min() if smaller else x.max())


def _close(got, want) -> bool:
    if pd.isna(want):
        return pd.isna(got)
    return not pd.isna(got) and math.isclose(float(got), want, rel_tol=1e-5, abs_tol=1e-300)


def test_runs_csv_is_recomputed_from_the_runs(decided):
    t = _load(decided / "w2")
    runs, lob, csv = t["runs"], t["lob"], t["csv"]
    assert list(csv.columns) == list(R.CSV_COLUMNS) and len(csv) == R.expected_counts(DECIDE)["total"]["csv"]
    assert (csv["label"] == R.LABEL).all()
    for bad in R.FORBIDDEN_CSV:
        assert not any(bad in c for c in csv.columns)
    for _, row in csv.iterrows():
        sel = (
            (runs["source"] == row["source"])
            & (runs["scope"] == row["scope"])
            & (runs["comparator"] == row["comparator"])
            & (runs["reading"] == row["reading"])
            & (runs["s"] == row["s"])
            & (runs["f"] == row["f"])
            & (runs["cap"] == row["cap"])
            & ((runs["R"] == row["R"]) | (runs["R"].isna() & pd.isna(row["R"])))
        )
        if row["comparator"] == "grid":
            sel &= runs["b"] == row["b"]
        mine = runs[sel]
        if row["comparator"] == "limit-only":
            bands = lob.set_index("run_id")
            mine = mine.drop(columns=list(R.BAND_KEYS)).join(bands[bands["b"] == row["b"]][list(R.BAND_KEYS)], on="run_id")
        assert row["n_windows"] == mine["window"].nunique() and row["n_failed"] == 0
        rolling = row["scope"] == "rolling"
        ref = mine[(mine["V"] == 5000.0) & (mine["cost"] == "1x")]
        for m in R.ONCE_METRICS:
            med, tail, worst = _agg(ref[m], m)
            assert _close(row[m], med), (row["source"], row["scope"], row["b"], row["cap"], m)
            assert _close(row[f"{m}_tail"], tail if rolling else math.nan)
            assert _close(row[f"{m}_worst"], worst if rolling else math.nan)
        for book, cost in R.PLAN_GRID.settings:
            at = mine[(mine["V"] == book) & (mine["cost"] == cost)]
            for m in R.SETTING_METRICS:
                name = f"{m}_{book:g}_{cost}"
                if at.empty:
                    assert pd.isna(row[name]) and pd.isna(row[f"{name}_tail"])
                    continue
                med, tail, worst = _agg(at[m], m)
                assert _close(row[name], med) and _close(row[f"{name}_tail"], tail if rolling else math.nan)
                assert _close(row[f"{name}_worst"], worst if rolling else math.nan)


# Independent versions of section 9's rules (numpy and plain Python; they share no code with holdmix's)


def _pool(runs, source):
    return runs[
        (runs["source"] == source)
        & (runs["scope"] == "rolling")
        & (runs["comparator"] == "grid")
        & (runs["reading"] == "lab")
        & runs["R"].isna()
    ]


def _limit_rows(runs, source):
    return runs[(runs["source"] == source) & (runs["scope"] == "rolling") & (runs["comparator"] == "limit-only")]


def _rule_b(pool, band):
    ref = pool[(pool["b"] == band) & (pool["V"] == 5000.0) & (pool["cost"] == "1x")]
    table = ref.pivot(index=["s", "f", "window"], columns="cap", values="out_days_per_year")
    stats, n_star = {}, "more than 8"
    for cap in H.FINITE_CAPS:
        x = (table[cap] - table["none"]).to_numpy()
        stats[cap] = (float(np.median(x)), float(np.percentile(x, 90)))
    for cap in reversed(H.FINITE_CAPS):  # loosest first: stop at the first that fails
        med, p90 = stats[cap]
        if not (med <= 7.0 and p90 <= 30.0):
            break
        n_star = cap
    return n_star, stats


def _acceptable(pool, band, cap, book, cost):
    ref = pool[(pool["b"] == band) & (pool["cap"] == cap) & (pool["V"] == 5000.0) & (pool["cost"] == "1x")]
    at = pool[(pool["b"] == band) & (pool["cap"] == cap) & (pool["V"] == book) & (pool["cost"] == cost)]
    rate, fees = float(np.median(ref["rebalances_per_30d"])), float(np.median(at["fees_pct_per_year"]))
    return rate <= 1.0 and fees <= 0.25, rate, fees


def _narrowest(ok: dict):
    best = "none"
    for b in sorted(ok, reverse=True):  # widest first
        if not ok[b]:
            break
        best = b
    return best


def _rank_band(b):
    return 99 if b == "none" else H.BANDS.index(b)


def _rank_cap(c):
    return 6 if c in ("more than 8", None) else H.FINITE_CAPS.index(c)


def _rule_c(pool, limit, book, cost):
    ref = pool[(pool["V"] == 5000.0) & (pool["cost"] == "1x")]
    at = pool[(pool["V"] == book) & (pool["cost"] == cost)]
    dist = {c: float(ref[ref["cap"] == c]["dist_mean"].mean()) for c in H.CAP_LABELS}
    dist_l = float(limit[(limit["V"] == 5000.0) & (limit["cost"] == "1x")]["dist_mean"].mean())
    fees = {c: float(at[at["cap"] == c]["fees_pct_per_year"].mean()) for c in H.CAP_LABELS}
    fees_l = float(limit[(limit["V"] == book) & (limit["cost"] == cost)]["fees_pct_per_year"].mean())
    den = dist_l - dist["none"]
    shares = {c: (dist_l - dist[c]) / den if den > 0 else None for c in H.CAP_LABELS}
    fden = fees["none"] - fees_l
    spent = {c: (fees[c] - fees_l) / fden if fden > 0 else None for c in H.CAP_LABELS}
    if not den > 0:
        return {"outcome": "NO EVIDENCE", "N_up": None, "I": shares, "C": spent, "Dist": dist, "F": fees}
    n_up = None
    for cap in reversed(H.FINITE_CAPS):
        if not shares[cap] >= 0.9:
            break
        n_up = cap
    out = {"outcome": "ABOVE 8" if n_up is None else "EVIDENCE FOR A LIMIT", "N_up": n_up, "I": shares, "C": spent}
    out.update(Dist=dist, Dist_L=dist_l, F=fees, F_L=fees_l)
    return out


def _value(i, c):
    return "SUPPORTED" if i is not None and c is not None and 1 - c >= 2 * (1 - i) else "WEAK"


def _close_dict(got: dict, want: dict) -> None:
    for key, value in want.items():
        g = got[str(key)]
        assert (g is None and value is None) or math.isclose(g, value, rel_tol=1e-12, abs_tol=1e-15), key


def test_decision_json_is_recomputed_from_the_runs(decided):
    t = _load(decided / "w2")
    runs, lob, d = t["runs"], t["lob"], t["decision"]
    assert d["label"] == R.LABEL and d["status"] == R.STATUS and d["decidable"] is True and d["rule_E"] is None
    assert d["thresholds"] == R.thresholds() and d["counts"]["got"]["runs"] == 1346 and d["failed_runs"] == 0
    settings = [(b, c) for c in H.COST_LABELS for b in H.BOOKS]
    own = {}
    for source in H.SOURCES:
        pool, limit = _pool(runs, source), _limit_rows(runs, source)
        src = d["sources"][source]
        stars = {}
        for b in H.BANDS:
            stars[b], stats = _rule_b(pool, b)
            assert src["N_star"][str(b)] == stars[b] and src["rule_B"][str(b)]["N_star"] == stars[b]
            for cap, (med, p90) in stats.items():
                got = src["rule_B"][str(b)]["caps"][cap]
                assert math.isclose(got["median"], med, rel_tol=1e-12, abs_tol=1e-12)
                assert math.isclose(got["p90"], p90, rel_tol=1e-12, abs_tol=1e-12)
        own[source] = {"stars": stars, "pool": pool, "limit": limit, "b_star": {}, "C": {}}
        for book, cost in settings:
            tag = f"{book:g}/{cost}"
            ok = {}
            for b in H.BANDS:
                if stars[b] in H.FINITE_CAPS:
                    ok[b], rate, fees = _acceptable(pool, b, stars[b], book, cost)
                    band = src["rule_A"][tag]["bands"][str(b)]
                    assert math.isclose(band["rate_median"], rate, rel_tol=1e-12) and math.isclose(band["fees_median"], fees, rel_tol=1e-12)
                else:
                    ok[b] = False
            b_star = _narrowest(ok)
            own[source]["b_star"][tag] = b_star
            assert src["rule_A"][tag]["b_star"] == b_star
            c = _rule_c(pool, limit, book, cost)
            own[source]["C"][tag] = c
            rc = src["rule_C"][tag]
            assert (rc["outcome"], rc["N_up"]) == (c["outcome"], c["N_up"])
            _close_dict(rc["Dist"], c["Dist"])
            _close_dict(rc["F"], c["F"])
            _close_dict(rc["I"], c["I"])
            _close_dict(rc["C"], c["C"])
            if c["outcome"] == "EVIDENCE FOR A LIMIT":
                assert rc["value_test"] == _value(c["I"][c["N_up"]], c["C"][c["N_up"]])
        for cost in H.COST_LABELS:
            widest = max((own[source]["b_star"][f"{b:g}/{cost}"] for b in H.BOOKS), key=_rank_band)
            assert src["app_default"][cost]["b_star"] == widest
    # rule D, by hand
    rob = d["robust"]
    k, b = own["KRAKEN"], own["BINANCE"]
    stars = {x: max(k["stars"][x], b["stars"][x], key=_rank_cap) for x in H.BANDS}
    assert rob["N_star"] == {str(x): v for x, v in stars.items()}
    b_star = {}
    for book in H.BOOKS:
        ok = {}
        for x in H.BANDS:
            ok[x] = stars[x] in H.FINITE_CAPS and all(
                _acceptable(own[s]["pool"], x, stars[x], book, c)[0] for s in H.SOURCES for c in H.COST_LABELS
            )
        b_star[book] = _narrowest(ok)
    assert rob["b_star"] == {str(x): v for x, v in b_star.items()}
    app = max(b_star.values(), key=_rank_band)
    assert rob["app_default"] == app
    outs = [own[s]["C"]["5000/1x"] for s in H.SOURCES]
    evidence = [o for o in outs if o["outcome"] != "NO EVIDENCE"]
    assert evidence or rob["outcome"] == "NO EVIDENCE"
    best = max(evidence, key=lambda o: _rank_cap(o["N_up"]) if o["outcome"] == "EVIDENCE FOR A LIMIT" else 6)
    assert (rob["outcome"], rob["N_up"]) == (best["outcome"], best["N_up"])
    if best["outcome"] == "EVIDENCE FOR A LIMIT":
        n = best["N_up"]
        tests = {f"{s} {c}": _value(own[s]["C"]["5000/1x"]["I"][n], own[s]["C"][f"5000/{c}"]["C"][n]) for s in H.SOURCES for c in H.COST_LABELS}
        assert rob["value_tests"] == tests
        assert rob["value_test"] == ("SUPPORTED" if set(tests.values()) == {"SUPPORTED"} else "WEAK")
        assert rob["held_back"] == [x for x in H.BANDS if _rank_cap(stars[x]) > _rank_cap(n)]
        conflict = app == "none" or _rank_cap(stars[app]) > _rank_cap(n)
        assert rob["conflict"] is conflict
    band = H.BANDS[-1] if app == "none" else app
    assert rob["headline"] == {"band": band, "cap": "none" if stars[band] == "more than 8" else stars[band]}
    primary = (
        {x: k["stars"][x] for x in H.BANDS},
        {book: k["b_star"][f"{book:g}/1x"] for book in H.BOOKS},
        max((k["b_star"][f"{book:g}/1x"] for book in H.BOOKS), key=_rank_band),
        (k["C"]["5000/1x"]["outcome"], k["C"]["5000/1x"]["N_up"]),
    )
    robust_values = (stars, b_star, app, (rob["outcome"], rob["N_up"]))
    same = primary == robust_values and d["sources"]["KRAKEN"]["rule_C"]["5000/1x"]["value_test"] == rob["value_test"]
    # A6: the CONFLICT flag and the default under the limit are headline values too
    under = rob["under_limit"]
    k_under = rob["primary_check"]["under_limit"]
    same = same and rob["primary_check"]["conflict"] == rob["conflict"]
    same = same and (None if k_under is None else (k_under["b_star"], k_under["cap"])) == (
        None if under is None else (under["b_star"], under["cap"])
    )
    assert rob["label"] == ("ROBUST" if same and len(evidence) != 1 else "NOT ROBUST")
    if rob["label"] == "NOT ROBUST":  # Kraken on Binance's windows (section 9, rule D)
        kob = d["kraken_on_binance_windows"]
        assert kob["windows"] == [59]
        kp = k["pool"][k["pool"]["window"] == 59]
        assert kob["decisions"]["N_star"] == {str(x): _rule_b(kp, x)[0] for x in H.BANDS}
        # every rule on window 59 alone, A and C included (#52)
        lo = H.limit_only_pool(runs, "KRAKEN")
        lb = H.limit_only_pool(lob, "KRAKEN")
        want = H.decide_source(kp, lo[lo["window"] == 59], limit_only_bands=lb[lb["window"] == 59])
        assert R.json_text(kob["decisions"]) == R.json_text(want)
        for book, cost in settings:
            tag = f"{book:g}/{cost}"
            c = _rule_c(kp, k["limit"][k["limit"]["window"] == 59], book, cost)
            assert (kob["decisions"]["rule_C"][tag]["outcome"], kob["decisions"]["rule_C"][tag]["N_up"]) == (
                c["outcome"],
                c["N_up"],
            )
    else:
        assert d["kraken_on_binance_windows"] is None
    # what holdmix's rules give on the parquet tables is what decision.json holds (the wiring)
    assert R.json_text(R.decide_sources(runs, lob)) == R.json_text(d["sources"])


def test_the_descriptions_and_the_per_share_table_are_recomputed(decided):
    t = _load(decided / "w2")
    runs, d = t["runs"], t["decision"]
    head = d["robust"]["headline"]
    for source in H.SOURCES:
        desc = d["descriptions"][source]
        pool = _pool(runs, source)
        for b in H.BANDS:
            ref = pool[(pool["b"] == b) & (pool["V"] == 5000.0) & (pool["cost"] == "1x")]
            table = ref.pivot(index=["s", "f", "window"], columns="cap", values="out_days_per_year")
            years = 2017 + table.index.get_level_values("window").to_numpy() // 12
            for y in sorted(set(years)):
                for cap in H.FINITE_CAPS:
                    x = (table[cap] - table["none"]).to_numpy()[years == y]
                    got = desc["years"][str(b)][str(int(y))][cap]
                    assert math.isclose(got["median"], float(np.median(x)), abs_tol=1e-12)
                    assert math.isclose(got["p90"], float(np.percentile(x, 90)), abs_tol=1e-12)
        assert desc["non_overlapping_windows"] == sorted(set(DECIDE.windows[source]) & {0, 12, 24, 36, 48})
        assert (desc["non_overlapping"]["0.05"] is None) == (source == "BINANCE")
        assert desc["limit_readings"]["cash"]["mixes"] == desc["limit_readings"]["together"]["mixes"] == 1
        other = desc["other_reading"]
        assert other is not None
        opool = runs[(runs["source"] == source) & (runs["scope"] == "rolling") & (runs["reading"] == "other")]
        nocap = pool[(pool["cap"] == "none") & (pool["V"] == 5000.0) & (pool["cost"] == "1x")]
        for b in H.BANDS:
            assert other["N_star"][str(b)] == _rule_b(pd.concat([opool, nocap]), b)[0]
        # per_share at the headline
        at = pool[(pool["b"] == head["band"]) & (pool["cap"] == head["cap"])]
        (row,) = d["per_share"][source]
        ref = at[(at["V"] == 5000.0) & (at["cost"] == "1x")]
        assert row["s"] == 0.5 and row["pairs"] == len(ref) == 2
        assert row["max_in_30d_median"] == float(np.median(ref["max_in_30d"]))
        assert row["max_in_30d_worst"] == float(ref["max_in_30d"].max())
        assert row["rebalances_per_30d_median"] == float(np.median(ref["rebalances_per_30d"]))
        assert row["out_days_per_year_median"] == float(np.median(ref["out_days_per_year"]))
        assert row["limit_in_wait_per_year_worst"] == float(ref["limit_in_wait_per_year"].max())
        for book in H.BOOKS:
            fees = at[(at["V"] == book) & (at["cost"] == "1x")]["fees_pct_per_year"]
            assert row["fees_pct_per_year_median_1x"][str(book)] == float(np.median(fees))


def test_the_reported_worst_falls_are_recomputed_from_the_runs(decided):
    """A3: each fall is -100 x the MINIMUM of the signed max_drawdown (the worst window named), never its 90th
    percentile or its median, and the full runs give their peak and trough."""
    t = _load(decided / "w2")
    runs, falls, d = t["runs"], t["falls"], t["decision"]
    head = d["robust"]["headline"]
    assert d["falls"]["headline"] == head and d["falls"]["rows"] == len(falls) == 4
    assert (falls["label"] == R.LABEL).all() and (falls["note"] == H.FALLS_NOTE).all()
    assert list(falls.columns) == list(H.FALLS_COLUMNS)
    discriminating = False
    for source in H.SOURCES:
        base = runs[(runs["source"] == source) & (runs["comparator"] == "grid") & (runs["reading"] == "lab") & (runs["V"] == 5000.0) & (runs["cost"] == "1x")]
        rolling = base[(base["scope"] == "rolling") & base["R"].isna()]
        at = rolling[(rolling["b"] == head["band"]) & (rolling["cap"] == head["cap"])]
        worst = at.loc[at["max_drawdown"].idxmin()]
        full = base[(base["scope"] == "full") & (base["b"] == head["band"]) & (base["cap"] == head["cap"])]
        f0, f365 = full[full["R"].isna()].iloc[0], full[full["R"] == 365].iloc[0]
        ties = rolling[rolling["max_drawdown"] == rolling["max_drawdown"].min()]
        deepest = ties.assign(_c=ties["cap"].map(H.CAP_LABELS.index)).sort_values(["b", "_c", "window"]).iloc[0]
        x = at["max_drawdown"].to_numpy()
        discriminating |= x.min() not in (np.median(x), np.percentile(x, 90))
        for level in ("share", "mix"):
            row = falls[(falls["source"] == source) & (falls["level"] == level)].iloc[0]
            assert not row["missing"]
            assert math.isclose(row["window_fall_pct"], -100 * worst["max_drawdown"], rel_tol=1e-5)
            assert row["window_k"] == worst["window"] and pd.Timestamp(row["window_first"]) == worst["first_close"]
            assert math.isclose(row["full_fall_pct"], -100 * f0["max_drawdown"], rel_tol=1e-5)
            assert pd.Timestamp(row["full_peak"]) == f0["mdd_peak"] and pd.Timestamp(row["full_trough"]) == f0["mdd_trough"]
            assert math.isclose(row["full_reset_fall_pct"], -100 * f365["max_drawdown"], rel_tol=1e-5)
            assert math.isclose(row["grid_fall_pct"], -100 * deepest["max_drawdown"], rel_tol=1e-5)
            assert (row["grid_b"], row["grid_cap"], row["grid_k"]) == (deepest["b"], deepest["cap"], deepest["window"])
            assert math.isclose(row["worst_day_pct"], -100 * f0["worst_day"], rel_tol=1e-5)
            assert pd.Timestamp(row["worst_day_close"]) == f0["worst_day_close"]
            assert math.isclose(row["worst_week_pct"], -100 * f0["worst_week"], rel_tol=1e-5)
            assert pd.Timestamp(row["worst_week_start"]) == f0["worst_week_start"]
            assert row["window_fall_pct"] > 0 and row["full_fall_pct"] > 0
    assert discriminating  # the minimum differs from the median and the 90th percentile somewhere


def test_a_failed_run_makes_the_decisions_it_feeds_missing_and_rule_e_drops_its_pair(decided, monkeypatch):
    monkeypatch.setattr(R, "BOOM_MIN_WINDOWS", 1)
    t = _load(decided / "w2")
    runs, lob = t["runs"], t["lob"]
    returns = _year_returns(t["start"])
    runs = runs.drop(columns=[c for c in runs.columns if c.startswith("vs_")])
    hit = (
        (runs["source"] == "KRAKEN")
        & (runs["window"] == 0)
        & (runs["b"] == 0.2)
        & (runs["cap"] == "1")
        & (runs["V"] == 5000.0)
        & (runs["cost"] == "1x")
        & (runs["reading"] == "lab")
    )
    assert hit.sum() == 1
    runs.loc[hit, "status"] = "failed"
    runs.loc[hit, list(R.METRIC_KEYS)] = math.nan
    bundles = R.decide_sources(runs, lob)
    assert bundles["KRAKEN"]["N_star"][0.2] == H.MISSING and bundles["BINANCE"]["N_star"][0.2] != H.MISSING
    assert bundles["KRAKEN"]["rule_C"]["5000/1x"]["outcome"] == H.MISSING
    rob = H.robust(bundles["KRAKEN"], bundles["BINANCE"])
    assert rob["label"] == H.MISSING and rob["headline"] == {"band": H.MISSING, "cap": H.MISSING}
    assert R.per_share(runs, rob["headline"]) is None
    e = R.rule_e(runs, lob, returns)
    assert e["failed_runs"] == 1 and e["dropped_pairs"] == [("KRAKEN", "rolling", 0, 0.5, 0.5)]
    kept = runs[~((runs["source"] == "KRAKEN") & (runs["scope"] == "rolling") & (runs["window"] == 0))]
    kept_lob = lob[~((lob["source"] == "KRAKEN") & (lob["scope"] == "rolling") & (lob["window"] == 0))]
    want = R.decide_sources(kept, kept_lob)
    assert R.json_text(e["sources"]) == R.json_text(want)
    rob = H.robust(want["KRAKEN"], want["BINANCE"])
    assert R.json_text(e["robust"]) == R.json_text(rob)
    # A5 on rule E's kept pairs: only removals that keep a Kraken window other than 0 can be computed
    boom = {r["name"]: r for r in e["boom_check"]["removals"]}
    assert R.json_text(e["boom_check"]) == R.json_text(R.boom_check(kept, kept_lob, returns, rob))
    # Kraken's window 0 is dropped, so each removal starts from window 59 alone: without 2021 or 2022 it keeps none
    assert {name: r["windows"]["KRAKEN"] for name, r in boom.items() if not name.startswith("best")} == {
        "2017": [59], "2018": [59], "2019": [59], "2020": [59], "2021": [], "2022": [],
    }
    assert boom["2021"]["status"] == H.MISSING and "'KRAKEN': 0" in boom["2021"]["reason"]
    k59 = R.decide_sources(kept, kept_lob, windows={"KRAKEN": [59], "BINANCE": [59]})
    assert R.json_text(boom["2018"]["robust"]) == R.json_text(H.robust(k59["KRAKEN"], k59["BINANCE"]))
    # a pool emptied by rule E is reported, not a crash: fail one more Kraken run, in its other window
    other = (
        (runs["source"] == "KRAKEN")
        & (runs["scope"] == "rolling")
        & (runs["window"] == 59)
        & (runs["b"] == 0.05)
        & (runs["cap"] == "8")
        & (runs["V"] == 500.0)
        & (runs["cost"] == "2x")
    )
    assert other.sum() == 1
    runs.loc[other, "status"] = "failed"
    emptied = R.rule_e(runs, lob, returns)
    assert emptied["failed_runs"] == 2 and len(emptied["dropped_pairs"]) == 2
    assert "cannot apply the rules" in emptied["error"] and "sources" not in emptied and "boom_check" not in emptied


def test_the_start_record_and_runlog_of_the_decided_run(decided):
    t = _load(decided / "w2")
    start, d = t["start"], t["decision"]
    assert start["grid"]["name"] == "test-decide" and start["grid"]["decidable"] is True
    assert start["fast"] is True and start["workers"] == 2 and start["interpretations"] == R.INTERPRETATIONS
    assert start["platform"]["sys_platform"] == sys.platform and start["platform"]["start_method"] == "fork"
    summary = read_json(decided / "w2" / "run0" / "summary.json")
    assert summary["status"] == "complete" and summary["headline"] == d["robust"]["headline"]
    assert summary["decision_tables"].startswith("decision.json")
    assert summary["grid"]["blocks"] == summary["grid"]["blocks_logged"] == 6
    assert summary["grid"]["runs_logged"] == summary["counts"]["runs"] == 1346
    assert summary["label_rule_D"] == d["robust"]["label"] and summary["checks"]["parity"] == 42
    log = runlog(decided / "w2" / "tracked" / "RUNLOG.jsonl")
    assert [e.get("event") for e in log] == [None, "complete"] and log[0]["config_hash"] == start["config_hash"]
    assert (decided / "w2" / "run0" / "decision.json").read_bytes() == (decided / "w2" / "tracked" / "decision.json").read_bytes()


# ------------------------------------------------- consistency stops and logging found by the code-breaker (#52)


def test_two_runs_with_one_run_id_stop_the_run(tmp_path, monkeypatch, tiny):
    """The last Kraken row takes the first row's run id: every count stays right, and only this stop sees it."""
    real = R._block

    def twin(source, scope, k):
        got = real(source, scope, k)
        if (source, scope) == ("KRAKEN", "rolling"):
            runs = got["runs"].copy()
            runs.loc[runs.index[-1], "run_id"] = runs["run_id"].iloc[0]
            got["runs"] = runs
        return got

    monkeypatch.setattr(R, "_block", twin)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "two runs share a run id" in _stopped(out, runs_logged=True)["status"]


def test_a_runs_csv_with_a_row_missing_stops_the_run(tmp_path, monkeypatch, tiny):
    real = R.runs_csv
    monkeypatch.setattr(R, "runs_csv", lambda runs, lob: real(runs, lob).iloc[:-1])
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert "runs.csv has" in _stopped(out, runs_logged=True)["status"]


@pytest.mark.parametrize("what", ["lob", "parity"])
def test_a_lost_band_row_or_parity_check_stops_the_run_at_the_count(tmp_path, monkeypatch, tiny, what):
    real = R._block

    def lossy(source, scope, k):
        got = real(source, scope, k)
        if (source, scope) == ("BINANCE", "rolling"):
            got[what] = got[what].iloc[:-1]
        return got

    monkeypatch.setattr(R, "_block", lossy)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    assert f"'{what}':" in _stopped(out, runs_logged=True)["status"]


def test_a_binance_close_missing_from_the_full_window_only_stops_before_any_backtest(tmp_path, monkeypatch):
    """2017-08-25 (inside the full window, before window 8's first close) missing and 2017-08-17 added: still 1963
    rows, every rolling window whole. Only the full window's check sees it, before any backtest."""
    gone, added = pd.Timestamp("2017-08-25", tz="UTC"), pd.Timestamp("2017-08-17", tz="UTC")

    def change(instrument, bars):
        if not instrument.endswith("BINANCE"):
            return bars
        extra = bars.iloc[[0]].copy()
        extra.index = pd.DatetimeIndex([added], name="ts").as_unit("us")
        return pd.concat([extra, bars.drop(gone)])

    monkeypatch.setattr(R, "synthetic_bar_loader", _reshaped(change))
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "5" and "BINANCE window -1:" in summary["status"]
    assert "2017-08-25" in summary["status"]


def test_the_limit_readings_hold_the_whole_pool_s_decisions_on_one_mix(decided):
    """The decided run's one mix (s = 0.5) is in both limit-reading subsets, so each is the whole pool: its rules A-C
    equal the source's own, limit-only band rows included (rule C's days-out-of-band block)."""
    d = _load(decided / "w2")["decision"]
    for source in H.SOURCES:
        assert d["sources"][source]["rule_C"]["5000/1x"]["days"] is not None
        for name in ("cash", "together"):
            got = d["descriptions"][source]["limit_readings"][name]["decisions"]
            assert R.json_text(got) == R.json_text(d["sources"][source])


def test_git_state_counts_untracked_files_but_not_ignored_ones(tmp_path, tmp_path_factory):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "a.txt").write_text("a\n")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    state = R.git_state(tmp_path)
    assert state["dirty"] is False and state["changes"] == [] and len(state["commit"]) == 40
    (tmp_path / "ignored.txt").write_text("x\n")
    assert R.git_state(tmp_path)["dirty"] is False
    (tmp_path / "new").mkdir()
    (tmp_path / "new" / "run.py").write_text("x\n")  # a new file in a new folder: listed one by one
    state = R.git_state(tmp_path)
    assert state["dirty"] is True and state["changes"] == ["?? new/run.py"]
    (tmp_path / "a.txt").write_text("b\n")
    assert sorted(R.git_state(tmp_path)["changes"]) == [" M a.txt", "?? new/run.py"]
    with pytest.raises(RuntimeError, match="git rev-parse HEAD failed"):  # not a git repo
        R.git_state(tmp_path_factory.mktemp("plain"))


@pytest.mark.parametrize("workers", [1, 2])
def test_a_stop_in_a_later_block_keeps_the_blocks_that_returned(tmp_path, monkeypatch, tiny, workers):
    """Stop rule 6: the Kraken block returns, the Binance block stops; the Kraken block's four tables stay in
    run0/blocks/ and summary.json counts them (INTERPRETATIONS["logging"])."""
    real = R._block

    def stopping(source, scope, k):
        if source == "BINANCE":
            raise R.Stop("8", "a synthetic stop in the last block")
        return real(source, scope, k)

    monkeypatch.setattr(R, "_block", stopping)
    out = tmp_path / "dry"
    assert R.main(dry(out, workers=workers)) == 3
    summary = _stopped(out)
    assert "a synthetic stop in the last block" in summary["status"]
    n = R.expected_counts(TINY)["per_source"]["KRAKEN"]
    folder = out / "run0" / "blocks"
    assert sorted(p.name for p in folder.iterdir()) == [
        f"KRAKEN-rolling-00.{table}.parquet" for table in ("failures", "lob", "parity", "runs")
    ]
    runs = pd.read_parquet(folder / "KRAKEN-rolling-00.runs.parquet")
    assert len(runs) == n["grid_rolling"] + n["other"] + n["limit_only"] == 7 and (runs["source"] == "KRAKEN").all()
    assert len(pd.read_parquet(folder / "KRAKEN-rolling-00.lob.parquet")) == n["lob"]
    parity = pd.read_parquet(folder / "KRAKEN-rolling-00.parity.parquet")
    assert len(parity) == n["parity_band"] + n["parity_limit"] == 2 and set(parity["outcome"]) == {"equal"}
    assert {k: summary["grid"][k] for k in ("blocks", "blocks_logged", "runs_logged")} == {
        "blocks": 2,
        "blocks_logged": 1,
        "runs_logged": 7,
    }
    # the logged rows are the rows a complete run reports
    full = tmp_path / "complete"
    monkeypatch.setattr(R, "_block", real)
    assert R.main(dry(full)) == 0
    complete = pd.read_parquet(full / "run0" / "runs.parquet")
    kraken = complete[complete["source"] == "KRAKEN"][list(runs.columns)].reset_index(drop=True)
    pd.testing.assert_frame_equal(R.sort_rows(runs, R.RUN_SORT).drop(columns="commit"), kraken.drop(columns="commit"))


def test_with_workers_a_block_already_running_when_another_stops_is_logged(tmp_path, monkeypatch, tiny):
    """With 2 workers the first block (Kraken) stops only after the second (Binance) has run: the Binance block
    finishes and is written, though it comes after the stop in task order."""
    marker = tmp_path / "binance-done"
    real = R._block

    def blocks(source, scope, k):
        if source == "KRAKEN":
            deadline = time.time() + 120
            while not marker.exists() and time.time() < deadline:
                time.sleep(0.02)
            raise R.Stop("8", "a synthetic stop in the first block")
        got = real(source, scope, k)
        marker.write_text("done")
        return got

    monkeypatch.setattr(R, "_block", blocks)
    out = tmp_path / "dry"
    assert R.main(dry(out, workers=2)) == 3
    summary = _stopped(out)
    assert "a synthetic stop in the first block" in summary["status"] and "('KRAKEN', 'rolling', 0)" in summary["status"]
    assert [p.name for p in _logged_blocks(out)] == ["BINANCE-rolling-59.runs.parquet"]
    assert summary["grid"]["blocks_logged"] == 1 and summary["grid"]["runs_logged"] == 7


def test_a_crash_in_the_decisions_keeps_the_four_tables(tmp_path, monkeypatch):
    """A crash after the grid (here in the decision rules) is recorded, and the four tables are already in run0/,
    runs.parquet with its comparison columns."""
    monkeypatch.setattr(R, "FAST", FAILING)

    def broken(*args, **kwargs):
        raise RuntimeError("a synthetic crash in the decisions")

    monkeypatch.setattr(R, "decisions", broken)
    out = tmp_path / "dry"
    with pytest.raises(RuntimeError, match="a synthetic crash in the decisions"):
        R.main(dry(out))
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"] == "crashed: RuntimeError: a synthetic crash in the decisions"
    assert [e.get("event") for e in runlog(out / "tracked" / "RUNLOG.jsonl")] == [None, "crashed"]
    n = R.expected_counts(FAILING)["total"]
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    assert len(runs) == n["runs"] == summary["grid"]["runs_logged"] and summary["grid"]["blocks_logged"] == 2
    assert all(f"vs_{w}_{m}" in runs.columns for w in ("nocap", "limit") for m in R.CMP_METRICS)
    assert len(pd.read_parquet(out / "run0" / "limit_only_bands.parquet")) == n["lob"]
    assert len(pd.read_parquet(out / "run0" / "parity.parquet")) == n["parity"]
    assert pd.read_parquet(out / "run0" / "failures.parquet").empty
    blocks = pd.concat([pd.read_parquet(b) for b in _logged_blocks(out)], ignore_index=True)
    pd.testing.assert_frame_equal(R.sort_rows(blocks, R.RUN_SORT), runs[list(blocks.columns)])
    assert not (out / "tracked" / "runs.csv").exists() and not (out / "run0" / "decision.json").exists()


def test_a_metric_that_fails_in_a_parity_configuration_is_a_failed_run_not_a_failed_parity_check(
    tmp_path, monkeypatch, tiny
):
    """trade_sizes raises for every run of Kraken's window 0 after the engine ran: those runs are logged as failed
    (stop rule 4) and their parity checks still compare the engine's own outcome."""
    monkeypatch.setattr(R, "measure_throughput", lambda limits, config_dir, reps: dict(TINY_TIMING))
    real = H.trade_sizes
    kraken_0 = pd.Timestamp("2017-01-02", tz="UTC")

    def broken(result):
        if result.index[0] == kraken_0:
            raise ValueError("a synthetic metric failure")
        return real(result)

    monkeypatch.setattr(H, "trade_sizes", broken)
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    failed = runs[runs["status"] == "failed"]
    assert len(failed) == 7 and set(failed["source"]) == {"KRAKEN"} and set(failed["window"]) == {0}
    assert set(failed["error"]) == {"ValueError: a synthetic metric failure"}
    parity = pd.read_parquet(out / "run0" / "parity.parquet")
    assert len(parity) == 4 and set(parity["outcome"]) == {"equal"}
    assert set(parity.loc[parity["source"] == "KRAKEN", "kind"]) == {"band", "limit-only"}


def test_a_tz_naive_close_after_the_train_window_is_stop_rule_3(tmp_path, monkeypatch):
    """A loader that returns a tz-naive index with a close after 2023-01-01 00:00: the guard reads it as UTC (stop
    rule 3), before load_panel sees the bars."""
    real_loader = R.synthetic_bar_loader

    def factory(seed):
        inner = real_loader(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            extra = bars.iloc[[-1]].copy()
            extra.index = pd.DatetimeIndex([pd.Timestamp("2023-01-02", tz="UTC")], name="ts").as_unit("us")
            out = pd.concat([bars, extra])
            out.index = out.index.tz_localize(None)
            out.attrs = bars.attrs
            return out

        return loader

    monkeypatch.setattr(R, "synthetic_bar_loader", factory)
    monkeypatch.setattr(R, "_block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "3" and "the loader returned a close 2023-01-02T00:00:00+00:00" in summary["status"]


# -------------------------------------------------------------------------- the boom-year addendum (A5)


def _year_returns(start: dict) -> dict:
    return {source: {int(y): v for y, v in r.items()} for source, r in start["year_returns"].items()}


def test_the_yearly_returns_are_recorded_before_any_backtest_and_recomputed_by_hand(tmp_path, monkeypatch, tiny):
    """start.json's year_returns: BTC's close at each year's end over the close a year before (bar days), Kraken's
    2017 from its first close 2017-01-02 and Binance's from 2017-08-18; written before any block runs."""
    out = tmp_path / "dry"
    seen = []
    real = R._block

    def watching(source, scope, k):
        seen.append("year_returns" in read_json(out / "run0" / "start.json"))
        return real(source, scope, k)

    monkeypatch.setattr(R, "_block", watching)
    assert R.main(dry(out)) == 0
    assert seen == [True, True]
    got = _year_returns(read_json(out / "run0" / "start.json"))
    want = panels()
    for source, first in (("KRAKEN", "2017-01-02"), ("BINANCE", "2017-08-18")):
        c = want[source][("BTC", "close")]
        ends = [pd.Timestamp(first, tz="UTC"), *(pd.Timestamp(f"{y + 1}-01-01", tz="UTC") for y in range(2017, 2023))]
        by_hand = {2017 + i: c[ends[i + 1]] / c[ends[i]] - 1.0 for i in range(6)}
        assert got[source] == by_hand == H.year_returns(want[source])


def test_the_boom_check_is_recomputed_from_the_runs(decided):
    """decision.json's boom_check (A5) on the decided run (BOOM_MIN_WINDOWS 1): the removals and their ranking, the
    kept windows from the months each window holds, rules A-D on the kept windows' logged runs, and every
    comparison with the headline, by hand."""
    t = _load(decided / "w2")
    runs, lob, d = t["runs"], t["lob"], t["decision"]
    boom = d["boom_check"]
    assert boom["label"] == H.BOOM_LABEL and "never in place of it" in boom["label"] and boom["status"] == R.STATUS
    assert boom["ranked_on"] == "KRAKEN" and boom["min_windows"] == 1
    returns = _year_returns(t["start"])
    assert {s: {int(y): v for y, v in r.items()} for s, r in boom["year_returns"].items()} == returns
    kraken = returns["KRAKEN"]
    ranked = sorted(kraken, key=lambda y: (-kraken[y], y))
    names = [r["name"] for r in boom["removals"]]
    assert names == ["2017", "2018", "2019", "2020", "2021", "2022", "best 1", "best 2"]
    years = {r["name"]: r["years"] for r in boom["removals"]}
    assert years["best 1"] == ranked[:1] and years["best 2"] == ranked[:2]
    head = d["robust"]

    def same(a, b):
        return "MISSING" if "MISSING" in (a, b) else a == b

    moved_somewhere = False
    for r in boom["removals"]:
        for source in H.SOURCES:  # a window goes when one of its 12 months is in a removed year
            want = [k for k in DECIDE.windows[source] if not any(2017 + (k + m) // 12 in r["years"] for m in range(12))]
            assert r["windows"][source] == want, (r["name"], source)
        if not all(r["windows"].values()):
            assert r["status"] == "MISSING" and r["robust"] is None and r["same_as_headline"] is None
            continue
        assert r["status"] == "ok"
        bundles = R.decide_sources(runs, lob, windows=r["windows"])
        rob = H.robust(bundles["KRAKEN"], bundles["BINANCE"])
        assert R.json_text(r["robust"]) == R.json_text(rob), r["name"]
        rr = r["robust"]
        want = {f"N*({b:g})": same(head["N_star"][str(b)], rr["N_star"][str(b)]) for b in H.BANDS}
        want.update({f"b*({v:g})": same(head["b_star"][str(v)], rr["b_star"][str(v)]) for v in H.BOOKS})
        want["app default"] = same(head["app_default"], rr["app_default"])
        want["N_up"] = same(H.outcome_label(head["outcome"], head["N_up"]), H.outcome_label(rr["outcome"], rr["N_up"]))
        want["value test"] = same(head["value_test"], rr["value_test"])
        want["CONFLICT"] = same(head["conflict"], rr["conflict"])
        want["all"] = "MISSING" if "MISSING" in want.values() else all(want.values())
        assert r["same_as_headline"] == want, r["name"]
        moved_somewhere |= want["all"] is False
    assert moved_somewhere  # some removal moves some value here, so the comparisons are not all trivially True
    assert {r["name"]: r["status"] for r in boom["removals"]}["2019"] == "ok"  # keeps every window: the headline
    assert all(v is True for v in {r["name"]: r for r in boom["removals"]}["2019"]["same_as_headline"].values())


def test_a_removal_that_leaves_too_few_windows_is_missing(decided, monkeypatch):
    """At the pinned minimum of 12 windows, every removal on the decided run's 2 windows a source is MISSING."""
    assert R.BOOM_MIN_WINDOWS == H.BOOM_MIN_WINDOWS == 12
    t = _load(decided / "w2")
    runs, lob = t["runs"], t["lob"]
    bundles = R.decide_sources(runs, lob)
    got = R.boom_check(runs, lob, _year_returns(t["start"]), H.robust(bundles["KRAKEN"], bundles["BINANCE"]))
    assert got["min_windows"] == 12 and len(got["removals"]) == 8
    for r in got["removals"]:
        assert r["status"] == H.MISSING and r["robust"] is None and r["same_as_headline"] is None
        assert r["reason"].startswith("fewer than 12 windows kept: {")
    assert R.pinned_values()["boom"] == {"years": list(H.TRAIN_YEARS), "ranked_on": "KRAKEN", "best": [1, 2], "min_windows": 12}
    monkeypatch.setattr(R, "BOOM_MIN_WINDOWS", 1)
    assert R.pinned_values()["boom"]["min_windows"] == 1  # the minimum is in the config hash


def test_the_years_are_ranked_on_kraken_s_closes_for_both_sources(decided, monkeypatch):
    """A5: the best years come from Kraken's yearly returns, whatever Binance's say (on synthetic data the two rank
    alike, so made-up returns that disagree are handed in here)."""
    monkeypatch.setattr(R, "BOOM_MIN_WINDOWS", 1)
    t = _load(decided / "w2")
    runs, lob = t["runs"], t["lob"]
    bundles = R.decide_sources(runs, lob)
    returns = {
        "KRAKEN": {2017: 13.0, 2018: -0.73, 2019: 0.95, 2020: 3.0, 2021: 0.6, 2022: -0.64},
        "BINANCE": {2017: 2.2, 2018: -0.73, 2019: 0.95, 2020: 3.0, 2021: 5.0, 2022: -0.64},
    }
    got = R.boom_check(runs, lob, returns, H.robust(bundles["KRAKEN"], bundles["BINANCE"]))
    best = {r["name"]: r["years"] for r in got["removals"] if r["name"].startswith("best")}
    assert best == {"best 1": [2017], "best 2": [2017, 2020]} and got["year_returns"] == returns
