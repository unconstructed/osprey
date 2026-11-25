"""The keep-risk-steady study script (``research/keep-risk-steady/run.py``) and its A0 pre-check (``controls.py``)
against PLAN.md sections 3-15: the start guards, the start record and RUNLOG line before any bar, the train-window
loader guard, the data stops, every run logged, the consistency stops of section 11, the blocks kept on a stop, and
every reported number recomputed from its inputs by an independent statement of sections 5-10 written here.

SYNTHETIC data only: every run is a ``--synthetic`` dry run in ``tmp_path`` (``--fast``, or a tiny grid put in its
place); the real catalog loader is replaced by one that fails the test if it is ever reached (except where a test hands
it synthetic bars on purpose), and the git state is injected. Real-data guards run against stand-ins for every folder a
real run uses and a stand-in PLAN.md (``real_folders``), so no test depends on what the repo has recorded so far
(TESTING.md #48, #59, #68).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_keeprisk import hand_resampler

from lab.data import catalog
from lab.data.panel import load_panel
from lab.runner import holdmix as H
from lab.runner import keeprisk as K
from lab.runner import protect as P
from lab.runner import trend as T

STUDY_DIR = Path(__file__).resolve().parents[1] / "research" / "keep-risk-steady"


def _load(name: str, file: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, STUDY_DIR / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


R = _load("keep_risk_steady_run", "run.py")
C = _load("keep_risk_steady_controls", "controls.py")

CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
SEED = 7
LIM = {"min_cash": 0.20, "max_coin": 0.60}
TINY_TIMING = {"cpu_minutes": 1.0, "a0_cpu_minutes": {"100": 1.0, "80": 1.0}, "reps": 1, "seconds": {}}
TINY = R.Grid(
    settings=(0.08,),
    mixes=((0.50, 0.50),),
    windows={"KRAKEN": (0,), "BINANCE": (48,)},
    families=("KRAKEN 1x",),
    copy_stride=128,
    resamples=50,
    name="test-tiny",
)
PLAN_TEXT = """# keep-risk-steady: stand-in plan

## 13. Protocol, stop rules and amendments

**Amendments:**
{rows}
## 14. Allowed range
"""
PLACEHOLDERS = (
    "- **A1** (to be written after the tiers pass on the build's commit; synthetic bars only).\n"
    '- **A0** (to be written after A1; synthetic only; it says "no alarm" or names the owner\'s decision).\n'
)
RECORDS = "- **A1** (2026-11-26): run 0 projects 28 CPU-minutes.\n- **A0** (2026-11-26): no alarm.\n"


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
    monkeypatch.setattr(R, "measure_throughput", lambda *a, **k: dict(TINY_TIMING))


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


def real_folders(monkeypatch, tmp_path: Path, rows: str = RECORDS) -> tuple[Path, Path, Path]:
    """Stand-ins for results/keep-risk-steady, data/catalog, this study's folder and its PLAN.md."""
    out, cat, here = (
        tmp_path / "results" / "keep-risk-steady",
        tmp_path / "data" / "catalog",
        tmp_path / "here",
    )
    here.mkdir(parents=True)
    plan = here / "PLAN.md"
    plan.write_text(PLAN_TEXT.format(rows=rows))
    monkeypatch.setattr(R, "DEFAULT_OUT", out)
    monkeypatch.setattr(R, "DEFAULT_CATALOG", cat)
    monkeypatch.setattr(R, "HERE", here)
    monkeypatch.setattr(R, "PLAN", plan)
    return out, cat, here


def real_args(out: Path, cat: Path, *extra: str) -> list[str]:
    return ["--out-dir", str(out), "--catalog-dir", str(cat), "--workers", "1", *extra]


def write_snapshot(cat: Path, bars_hash: str = R.BARS_SHA256, snapshot_id: str = "synthetic") -> None:
    cat.mkdir(parents=True, exist_ok=True)
    (cat / catalog.SNAPSHOT_FILE).write_text(
        json.dumps({"snapshot_id": snapshot_id, "bars_content_sha256": bars_hash})
    )


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(root).rglob("*"))
        if p.is_file()
    }


def panels(seed: int = SEED) -> dict[str, pd.DataFrame]:
    loader = R.synthetic_bar_loader(seed)
    return {
        s: load_panel(s, "1d", last_close=R.LAST_CLOSE, catalog_dir="unused", loader=loader)
        for s in H.SOURCES
    }


# ------------------------------------------------------------------------------------------------ pinned values


def _mondays(index: pd.DatetimeIndex, lookback: int) -> int:
    return sum(1 for r, ts in enumerate(index) if r >= lookback and ts.day_of_week == 0)


def test_the_plan_s_counts_and_grids_are_pinned():
    c = R.expected_counts(R.PLAN_GRID)
    fam = c["families"]
    assert c["total"] == 117_760  # section 7
    assert fam["KRAKEN 1x"] == {"windows": 32 * 49 * 4, "spans": 32 * 520, "copies_per_cell": 258}
    assert fam["KRAKEN 2x"] == fam["KRAKEN 1x"]
    assert fam["BINANCE 1x"] == {"windows": 32 * 41 * 4, "spans": 32 * 454, "copies_per_cell": 225}
    assert (
        sum(fam[n]["windows"] + fam[n]["spans"] for n in ("KRAKEN 1x", "BINANCE 1x", "KRAKEN 2x"))
        == 17_792 + 47_808
    )
    assert fam["KRAKEN 1x L7"]["windows"] + fam["KRAKEN 1x L7"]["spans"] == 22_976
    assert fam["KRAKEN 1x L28"]["windows"] + fam["KRAKEN 1x L28"]["spans"] == 22_784
    assert fam["KRAKEN 1x 500 USD"]["windows"] + fam["KRAKEN 1x 500 USD"]["spans"] == 6_400
    kraken = T.train_grid()
    binance = pd.date_range("2017-08-18", "2023-01-01", freq="D", tz="UTC")
    assert (
        R.CHECKS
        == {
            ("KRAKEN", 14): _mondays(kraken, 14),
            ("KRAKEN", 7): _mondays(kraken, 7),
            ("KRAKEN", 28): _mondays(kraken, 28),
            ("BINANCE", 14): _mondays(binance, 14),
        }
        == {("KRAKEN", 14): 311, ("KRAKEN", 7): 312, ("KRAKEN", 28): 309, ("BINANCE", 14): 278}
    )
    assert kraken[14] == pd.Timestamp("2017-01-16", tz="UTC") and binance[17] == pd.Timestamp(
        "2017-09-04", tz="UTC"
    )
    assert len(R.tasks(R.PLAN_GRID)) == 6 * 32 + 49 * 5 + 41
    assert (
        R.PLAN_GRID.settings == K.W_VALUES and R.PLAN_GRID.mixes == K.MIXES and R.PLAN_GRID.copy_stride == 1
    )
    assert R.PLAN_GRID.windows == {"KRAKEN": tuple(range(49)), "BINANCE": tuple(range(8, 49))}
    assert R.FAST.settings == K.W_VALUES and R.FAST.resamples == 500 and R.FAST.copy_stride == 64
    assert (R.CPU_MINUTES_MAX, R.A0_CPU_MINUTES_MAX, R.MAX_AMENDMENTS, R.STRESS, R.BOOK_CHECK_EVERY) == (
        240.0,
        300.0,
        2,
        2.0,
        9,
    )
    assert R.ROWS == {"KRAKEN": 2190, "BINANCE": 1963} and R.SNAPSHOT_ID == "1746a21b75683e76"
    assert R.BARS_SHA256 == "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"
    assert R.PANEL_HASHES == {
        "KRAKEN": "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
        "BINANCE": "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
    }
    assert (R.TIMING_PANEL, R.TIMING_CELL) == (399999, (0.08, 0.60, 0.50))
    assert R.ROWSET_NAMES == (
        "all",
        *(f"without {y}" for y in range(2017, 2023)),
        "without the best 1",
        "without the best 2",
    )


def test_the_hashed_files_and_the_config_hash_move_with_them():
    paths = R.frozen_paths()
    for listed in (  # section 11's list
        "lab/runner/keeprisk.py",
        "lab/runner/volsteady.py",
        "lab/runner/trend.py",
        "lab/runner/protect.py",
        "lab/runner/holdmix.py",
        "lab/runner/portfolio.py",
        "lab/runner/reference.py",
        "lab/runner/steady.py",
        "lab/validation/stats.py",
        "lab/validation/montecarlo.py",
        "lab/data/panel.py",
        "lab/data/catalog.py",
        "lab/data/external.py",
        "lab/data/loaders.py",
        "lab/runner/interface.py",
        "lab/config.py",
        "config/costs.yaml",
        "config/splits.yaml",
        "config/risk_levels.yaml",
        "pyproject.toml",
        "uv.lock",
        "research/keep-risk-steady/run.py",
        "research/keep-risk-steady/controls.py",
        "research/keep-risk-steady/PLAN.md",
    ):
        assert listed in paths
    assert "lab/runner/__init__.py" not in paths  # keeprisk is not registered there (section 12)
    hashes = R.file_hashes()
    assert set(hashes) == set(paths)
    base = R.config_hash(hashes)
    moved = dict(hashes)
    moved["lab/runner/keeprisk.py"] = "0" * 64
    assert R.config_hash(moved) != base and R.config_hash(dict(hashes)) == base


# ------------------------------------------------------------------------------------------------ start guards


def _refused(capsys, code: int, text: str) -> None:
    assert code == 2
    assert text in capsys.readouterr().err


def test_start_guards_refuse_before_anything_is_written(tmp_path, capsys, clean_git, tiny):
    out = tmp_path / "out"
    _refused(capsys, R.main(["--fast", "--out-dir", str(out)]), "--fast is for synthetic dry runs only")
    _refused(capsys, R.main(dry(out, "--amendment", "0")), "--amendment 0")
    _refused(capsys, R.main(dry(out, workers=0)), "--workers 0")
    _refused(capsys, R.main(dry(R.DEFAULT_OUT)), "never writes into")
    _refused(capsys, R.main(dry(R.REPO / "scratch")), "never writes into")
    _refused(capsys, R.main(dry(out, "--amendment", "1")), "run0/start.json does not exist")
    _refused(capsys, R.main(dry(out, "--amendment", "3")), "numbered 1..2")
    assert not out.exists()
    (out / "run0").mkdir(parents=True)
    _refused(capsys, R.main(dry(out)), "already holds a run folder")
    (out / "run0" / "start.json").write_text(json.dumps({"data": "synthetic", "fast": False}))
    _refused(capsys, R.main(dry(out, "--amendment", "1")), "run 0 was a synthetic run (fast False)")
    (out / "run0" / "start.json").write_text("not json")
    _refused(capsys, R.main(dry(out, "--amendment", "1")), "cannot read run 0's start record")
    (out / "run1").mkdir()
    _refused(capsys, R.main(dry(out, "--amendment", "1")), "exists (a run is never resumed")
    log = out / "tracked" / "RUNLOG.jsonl"
    log.parent.mkdir()
    R.append_runlog(log, {"script": "run.py", "run": 2, "data": "synthetic", "utc": "x"})
    (out / "run1" / "start.json").write_text(json.dumps({"data": "synthetic", "fast": True}))
    (out / "run0" / "start.json").write_text(json.dumps({"data": "synthetic", "fast": True}))
    _refused(capsys, R.main(dry(out, "--amendment", "2")), "already records synthetic run 2")
    assert sorted(p.name for p in out.iterdir()) == ["run0", "run1", "tracked"]
    _refused(
        capsys,
        R.main(["--time", "--synthetic", "1", "--out-dir", str(tmp_path / "t")]),
        "--time runs on its own",
    )


def test_real_runs_use_the_pinned_folders_and_the_guards_in_order(tmp_path, capsys, monkeypatch, tiny):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(DIRTY))
    _refused(capsys, R.main(real_args(tmp_path / "elsewhere", cat)), "a real run writes only to")
    _refused(capsys, R.main(real_args(out, tmp_path / "cat2")), "a real run reads only")
    _refused(capsys, R.main(real_args(out, cat, "--config-dir", str(tmp_path))), "reads config/ only")
    _refused(capsys, R.main(real_args(out, cat)), "the git tree is dirty")
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(CLEAN))
    _refused(capsys, R.main(real_args(out, cat)), "cannot read")  # no SNAPSHOT.json in the stand-in catalog
    write_snapshot(cat, bars_hash="f" * 64)
    _refused(capsys, R.main(real_args(out, cat)), "is not 08f5ca2c")
    write_snapshot(cat, snapshot_id="")
    _refused(capsys, R.main(real_args(out, cat)), "names no snapshot_id")
    assert not out.exists() and sorted(p.name for p in here.iterdir()) == ["PLAN.md"]
    out.mkdir(parents=True)
    _refused(capsys, R.main(real_args(out, cat)), "run 0 runs once")
    (out / "run0").mkdir()
    (out / "run0" / "start.json").write_text(json.dumps({"data": "real", "fast": False}))
    _refused(capsys, R.main(real_args(out, cat, "--amendment", "1")), "lists no '- **Amendment run 1' row")


def test_prior_amendments_stop_rule_8(tmp_path, capsys, monkeypatch, clean_git, tiny):
    for i, (rows, text) in enumerate(
        (
            (
                PLACEHOLDERS,
                "needs exactly one '- **A1' record",
            ),  # the committed placeholders (the A0 one quotes "no alarm")
            (RECORDS + "- **A1** a second record.\n", "found 2 line(s)"),
            (
                "- **A1** (2026-11-26): timed.\n- **A0** (2026-11-26): alarms A0-1.\n",
                "says neither 'no alarm'",
            ),
            (
                "- **A1** timed.\n- **A0** owner decision: reports/director/no-such-file.md\n",
                "does not exist",
            ),
            ("- **A1** timed.\n", "needs exactly one '- **A0' record"),
        )
    ):
        out, cat, _ = real_folders(monkeypatch, tmp_path / str(i), rows=rows)
        write_snapshot(cat)
        _refused(capsys, R.main(real_args(out, cat)), text)
        assert not out.exists()
    with pytest.raises(R.Refusal, match="no amendments list"):
        R.prior_amendments("# a plan without section 13\n")
    got = R.prior_amendments(PLAN_TEXT.format(rows=RECORDS))
    assert got["owner_decision"] is None and got["A0"].endswith("no alarm.")
    decision = "- **A1** timed.\n- **Amendment A0** owner decision: reports/director/answer.md\n"
    (tmp_path / "reports" / "director").mkdir(parents=True)
    (tmp_path / "reports" / "director" / "answer.md").write_text("the owner's answer")
    assert (
        R.prior_amendments(PLAN_TEXT.format(rows=decision), tmp_path)["owner_decision"]
        == "reports/director/answer.md"
    )
    assert R.amendment_row_present(PLAN_TEXT.format(rows="- **Amendment run 1** (2026-12-01): a fix.\n"), 1)
    assert not R.amendment_row_present("- **Amendment run 1** outside the list\n## 14.\n", 1)


def test_the_steady_limits_and_the_grid_s_targets(tmp_path, capsys):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in ("costs.yaml", "splits.yaml"):
        (cfg / name).write_text((R.REPO / "config" / name).read_text())
    text = (R.REPO / "config" / "risk_levels.yaml").read_text()
    (cfg / "risk_levels.yaml").write_text(text.replace("max_coin_pct: 60", "max_coin_pct: 55", 1))
    with pytest.raises(R.Refusal, match="not the plan's 0.2 and 0.6"):
        R.steady_limits(cfg)
    (cfg / "risk_levels.yaml").write_text("steady: 3\n")
    with pytest.raises(R.Refusal, match="does not read"):
        R.steady_limits(cfg)
    assert R.check_grid_targets(R.FAST.mixes, LIM) == 5 * (8 + 2)
    with pytest.raises(R.Refusal, match="refuse a target of the grid"):
        R.check_grid_targets((), {"min_cash": 0.20, "max_coin": 0.40})


def test_the_projection_guard(tmp_path, capsys, monkeypatch, clean_git):
    out, cat, _ = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    monkeypatch.setattr(R, "PLAN_GRID", TINY)
    monkeypatch.setattr(R, "measure_throughput", lambda *a, **k: {**TINY_TIMING, "cpu_minutes": 240.000001})
    _refused(capsys, R.main(real_args(out, cat)), "stop rule 7: the projection is 240.0")
    assert not out.exists()
    monkeypatch.setattr(R, "measure_throughput", lambda *a, **k: {**TINY_TIMING, "cpu_minutes": 240.0})
    monkeypatch.setattr(catalog, "load_bars", R.synthetic_bar_loader(SEED))  # synthetic bars on purpose
    assert R.main(real_args(out, cat)) == 3  # exactly 240 starts; then the synthetic panel's hash stops it
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "2" and "panel hash" in summary["stop"]["message"]

    def broken(*a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(R, "measure_throughput", broken)
    out2, cat2, _ = real_folders(monkeypatch, tmp_path / "b")
    write_snapshot(cat2)
    _refused(capsys, R.main(real_args(out2, cat2)), "the A1 timing failed: RuntimeError: engine down")


def test_the_a1_timing_writes_its_projection_to_a_scratch_folder(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(R, "measure_throughput", lambda *a, **k: dict(TINY_TIMING))
    assert R.main(["--time", "--out-dir", str(tmp_path / "t")]) == 0
    assert read_json(tmp_path / "t" / "timing.json")["timing"]["cpu_minutes"] == 1.0
    _refused(capsys, R.main(["--time", "--out-dir", str(R.REPO / "t")]), "never writes into")


def test_the_projection_by_hand():
    per = {"span": 0.01, "copy": 0.02, "a0_copy": 0.015, "window": 0.005, "index_set": 0.5, "risk_x": 0.25}
    got = R.project(per)
    assert got["counts"] == {
        "span_runs": 6 * 32 * 4,
        "copy_pairs": 32 * (258 + 225 + 258 + 259 + 256),
        "window_runs": 32 * 4 * (49 * 5 + 41),
        "index_sets": 10,
        "resamplings": 32 * (9 + 5),
    }
    c = got["counts"]
    assert c["span_runs"] + 2 * c["copy_pairs"] + c["window_runs"] == 117_760
    want = (768 * 0.01 + c["copy_pairs"] * 0.02 + c["window_runs"] * 0.005 + 10 * 0.5 + 448 * 0.25) / 60
    assert got["cpu_minutes"] == pytest.approx(want, rel=1e-12)
    panel = 4 * (3 * 0.01 + 258 * 0.015) + 588 * 0.005 + 4 * 0.25
    assert got["a0_cpu_minutes"]["100"] == pytest.approx((500 * panel + 0.5) / 60, rel=1e-12)
    assert got["a0_cpu_minutes"]["80"] == pytest.approx((400 * panel + 0.5) / 60, rel=1e-12)


def test_the_real_timing_runs_on_synthetic_bars_only():
    got = R.measure_throughput(LIM, None, 1)
    assert set(got["seconds"]) == {"span", "copy", "a0_copy", "window", "index_set", "risk_x"}
    assert got["cpu_minutes"] > 0 and got["limit_cpu_minutes"] == 240.0 and got["reps"] == 1


# ------------------------------------------------------------------------------------------------ the data


def test_the_start_record_and_the_runlog_line_come_before_any_bar(tmp_path, monkeypatch, clean_git, tiny):
    out = tmp_path / "out"
    seen = {}
    inner = R.synthetic_bar_loader(SEED)

    def loader(seed):
        def call(instrument, interval, start=None, end=None, catalog_dir=None):
            if not seen:
                seen["start"] = (out / "run0" / "start.json").is_file()
                seen["log"] = R.runlog_entries(out / "tracked" / "RUNLOG.jsonl")
            seen.setdefault("ends", []).append(pd.Timestamp(end) if end is not None else None)
            return inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)

        return call

    monkeypatch.setattr(R, "synthetic_bar_loader", loader)
    assert R.main(dry(out)) == 0
    assert seen["start"] and len(seen["log"]) == 1 and seen["log"][0]["run"] == 0
    assert all(e is not None and e <= R.LAST_CLOSE for e in seen["ends"])  # the train window only
    start = read_json(out / "run0" / "start.json")
    assert start["year_returns"] and start["panels"]["KRAKEN"]["rows"] == 2190
    assert start["interpretations"] == R.INTERPRETATIONS and start["grid"]["name"] == "test-tiny"
    assert [e.get("event") for e in R.runlog_entries(out / "tracked" / "RUNLOG.jsonl")] == [None, "complete"]


@pytest.mark.parametrize("naive", [False, True])
def test_a_bar_after_the_train_window_is_stop_rule_3(tmp_path, monkeypatch, clean_git, tiny, naive):
    inner = R.synthetic_bar_loader(SEED)

    def leaky(seed):
        def call(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=None, catalog_dir=catalog_dir)
            extra = bars.iloc[-1:].copy()
            extra.index = pd.DatetimeIndex([pd.Timestamp("2023-01-02", tz="UTC")], name="ts").as_unit("us")
            out_ = pd.concat([bars, extra])
            if naive:
                out_.index = out_.index.tz_localize(None)
            out_.attrs = bars.attrs
            return out_

        return call

    monkeypatch.setattr(R, "synthetic_bar_loader", leaky)
    out = tmp_path / "out"
    assert R.main(dry(out)) == 3
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == "3" and "after the last train close" in summary["stop"]["message"]
    assert R.runlog_entries(out / "tracked" / "RUNLOG.jsonl")[-1]["event"] == "stop rule 3"
    assert not (out / "run0" / "runs.parquet").exists()


def test_the_data_stops(tmp_path, monkeypatch, clean_git, tiny):
    p = panels()
    with pytest.raises(R.Stop, match="2189 rows, expected 2190"):
        R.check_panel("KRAKEN", p["KRAKEN"].drop(index=p["KRAKEN"].index[5]), True)
    hole = p["BINANCE"].drop(index=p["BINANCE"].index[300])
    extra = p["BINANCE"].iloc[:1].copy()
    extra.index = pd.DatetimeIndex([pd.Timestamp("2017-08-17", tz="UTC")], name="ts").as_unit("us")
    same_rows = pd.concat([extra, hole])
    same_rows.attrs = hole.attrs
    with pytest.raises(R.Stop, match="BINANCE window"):
        R.check_panel("BINANCE", same_rows, True)
    with pytest.raises(R.Stop, match="panel hash"):
        R.check_panel("KRAKEN", p["KRAKEN"], False)
    R.check_panel("KRAKEN", p["KRAKEN"], True)

    def refusing(seed):
        def call(*a, **k):
            raise ValueError("bad bars")

        return call

    monkeypatch.setattr(R, "synthetic_bar_loader", refusing)
    out = tmp_path / "out"
    assert R.main(dry(out)) == 3
    assert read_json(out / "run0" / "summary.json")["stop"]["rule"] == "2"


def test_the_rowsets_and_the_sigma_recheck(monkeypatch):
    p = panels()["KRAKEN"]
    returns = H.year_returns(p)
    masks = R.rowset_masks(p, returns)
    assert list(masks) == list(R.ROWSET_NAMES)
    years = T.bar_years(p.index[1:])
    assert masks["all"].all() and len(masks["all"]) == 2189
    for y in range(2017, 2023):
        assert np.array_equal(masks[f"without {y}"], years != y)
    best = sorted(returns, key=lambda y: (-returns[y], y))
    assert np.array_equal(masks["without the best 1"], years != best[0])
    assert np.array_equal(masks["without the best 2"], ~np.isin(years, best[:2]))
    assert list(R.rowset_masks(p, None)) == ["all"]
    sig = K.swing(p, 0.5)
    got = R.sigma_recheck(p, sig, 0.5, 14, [0, 30], K.W_VALUES)
    assert got["rows"] == 311 + 1
    bad = sig.copy()
    bad[14] *= 1 + 1e-10
    with pytest.raises(R.Stop, match="sigma at row 14"):
        R.sigma_recheck(p, bad, 0.5, 14, [], K.W_VALUES)
    monkeypatch.setattr(K, "_q", lambda s, t: 0.123)
    with pytest.raises(R.Stop, match="q at row"):
        R.sigma_recheck(p, sig, 0.5, 14, [], K.W_VALUES)


def test_the_sigma_recheck_lists_a_near_integer_case_and_lets_the_engine_stand():
    idx = pd.date_range("2017-01-02", periods=30, freq="D", tz="UTC", name="ts")
    flat = R.pf.make_panel(
        {
            a: pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)
            for a in ("BTC", "ETH")
        },
        snapshot_id="t",
    )
    sig = np.full(30, np.nan)
    tau = K.level(0.10)
    x = K.basket_returns(flat, 0.5)
    assert (x[1:] == 0).all()
    sig[14:] = 0.0  # the engine's sigma of a flat window: numpy agrees (0); q = 1, not near an integer
    assert R.sigma_recheck(flat, sig, 0.5, 14, [], (0.10,))["near_integer"] == []
    p = panels()["KRAKEN"]
    s = K.swing(p, 0.5)
    c = 14
    w = s[c] / (2.0 * K.WEEK_TO_YEAR)  # 4 tau / sigma = 2 up to round-off
    got = R.sigma_recheck(p, s, 0.5, 14, [], (w,))
    assert {"row": c, "w": w, "f": 0.5, "lookback": 14} in got["near_integer"] and tau > 0


# ------------------------------------------------------------------------------------------------ the decided dry run


@pytest.fixture(scope="module")
def dry_runs(tmp_path_factory):
    """The --fast dry run (seed 7) with 1 and with 2 workers."""
    base = tmp_path_factory.mktemp("dry")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(R, "git_state", lambda repo=R.REPO: dict(CLEAN))
        mp.setattr(R, "TIMING_REPS_FAST", 1)
        for workers in (1, 2):
            assert R.main(dry(base / f"w{workers}", workers=workers)) == 0
    return base


def tables(base: Path, workers: int = 1) -> dict:
    run = base / f"w{workers}" / "run0"
    return {
        "runs": pd.read_parquet(run / "runs.parquet"),
        "series": pd.read_parquet(run / "series.parquet"),
        "spans": pd.read_parquet(run / "spans.parquet"),
        "decision": read_json(run / "decision.json"),
        "summary": read_json(run / "summary.json"),
        "start": read_json(run / "start.json"),
    }


def test_workers_1_and_2_give_byte_identical_outputs(dry_runs):
    a, b = dry_runs / "w1" / "tracked", dry_runs / "w2" / "tracked"
    for name in ("decision.json", "runs.csv", "spans.csv"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    assert tables(dry_runs, 1)["runs"].drop(columns=[]).equals(tables(dry_runs, 2)["runs"])


def test_every_run_is_logged_and_the_counts_are_section_7_s(dry_runs):
    t = tables(dry_runs)
    runs = t["runs"]
    want = R.expected_counts(R.FAST)
    assert len(runs) == want["total"] == t["decision"]["counts"]["got"] == t["summary"]["counts"]["expected"]
    for name, c in want["families"].items():
        mine = runs[runs["family"] == name]
        assert (mine["scope"] == "window").sum() == c["windows"] and (mine["scope"] == "span").sum() == c[
            "spans"
        ]
        cells = len(R.FAST.settings) * len(R.FAST.mixes)
        if R.FAMILY[name].copies:
            assert (
                (mine["kind"] == "copy").sum()
                == (mine["kind"] == "copy_X").sum()
                == cells * c["copies_per_cell"]
            )
    assert runs["run_id"].is_unique and (runs["status"] == K.OK).all()
    assert t["summary"]["status"] == "complete" and t["summary"]["blocks"]["logged"] == len(R.tasks(R.FAST))
    blocks = dry_runs / "w1" / "run0" / "blocks"
    assert len(list(blocks.glob("*.runs.parquet"))) == len(R.tasks(R.FAST))
    csv = pd.read_csv(dry_runs / "w1" / "tracked" / "runs.csv")
    assert list(csv.columns) == list(R.CSV_COLUMNS) and len(csv) == (runs["scope"] == "window").sum()
    assert not any(c in col.lower() for col in csv.columns for c in R.FORBIDDEN_CSV)
    spans_csv = pd.read_csv(dry_runs / "w1" / "tracked" / "spans.csv")
    assert len(spans_csv) == len(t["spans"]) == 4 * 2 * (9 + 5)


def _sigma(x, c, lookback):
    return float(np.std(x[c - lookback + 1 : c + 1], ddof=1)) * math.sqrt(365.0)


def _q(sigma, tau):
    m = 1.0 if sigma == 0 else min(1.0, tau / sigma)
    return math.floor(m * 4.0 + 1e-9) / 4.0


def my_q_path(panel, w, f, start, stop, lookback):
    """Sections 5.1-5.5 written out here: numpy's sigma, the switch-on decision, the Monday checks."""
    c = panel[("BTC", "close")].to_numpy()
    e = panel[("ETH", "close")].to_numpy()
    x = np.concatenate([[np.nan], np.log1p(f * (c[1:] / c[:-1] - 1.0) + (1.0 - f) * (e[1:] / e[:-1] - 1.0))])
    tau = w * math.sqrt(365.0 / 7.0)
    q = np.empty(stop - start)
    now = _q(_sigma(x, start, lookback), tau) if start >= lookback else 1.0
    for t in range(start, stop):
        if t > start and t >= lookback and panel.index[t].day_of_week == 0:
            now = _q(_sigma(x, t, lookback), tau)
        q[t - start] = now
    return q


def _exact_mean(a):
    return float(sum(Fraction(v) for v in a) / len(a))


def test_every_window_number_is_recomputed_from_the_runs_and_the_q_path(dry_runs):
    runs = tables(dry_runs)["runs"]
    p = panels()
    win = runs[runs["scope"] == "window"]
    for (fam, _k, w, s, f), cell in win.groupby(["family", "window", "w", "s", "f"]):
        by = {r.kind: r for r in cell.itertuples()}
        rule, n, x, eq = by["rule"], by["N"], by["X"], by["X_eq"]
        family = R.FAMILY[fam]
        panel = p[family.source]
        r0 = int(panel.index.get_loc(rule.first_close))
        q = my_q_path(panel, w, f, r0, r0 + rule.rows, family.lookback)
        assert (
            rule.x == _exact_mean((s * q)[:-1]) == x.share
        )  # section 6's x, from the q path recomputed here
        assert rule.V_X == math.log(rule.DD) - math.log(x.DD) and rule.V_N == math.log(rule.DD) - math.log(
            n.DD
        )
        assert rule.c_N == 100.0 * (n.cagr - rule.cagr) and rule.c_X == 100.0 * (x.cagr - rule.cagr)
        assert rule.c_eq == 100.0 * (eq.cagr - rule.cagr) and rule.x_eq == rule.x * math.exp(rule.V_X)
        assert rule.q_lt1 == float((q[:-1] < 1.0).mean()) and rule.q_le_half == float((q[:-1] <= 0.5).mean())
        assert n.share == s and rule.realised_gap == rule.realised - x.realised
        assert rule.rows in (729, 730, 731) and (rule.year == rule.first_close.year)


def _rerun(row, p, costs):
    """One logged run rebuilt from scratch with keeprisk, from its keys alone."""
    family = R.FAMILY[row.family]
    panel = p[family.source]
    c = costs[(family.cost, family.wallet)]
    if row.scope == "window":
        r0 = int(panel.index.get_loc(row.first_close))
        bars, qp = (
            panel.iloc[r0 : r0 + row.rows],
            K.q_path(panel, row.w, row.f, start=r0, stop=r0 + row.rows, lookback=family.lookback),
        )
    else:
        bars, qp = panel, K.q_path(panel, row.w, row.f, lookback=family.lookback)
    share = row.s * qp.q
    x = K.matched_share(share)
    if row.kind == "rule":
        res = K.run_rule(bars, qp, row.s, row.f, limits=LIM, costs=c)
    elif row.kind in ("N", "X", "X_eq"):
        if row.kind == "X_eq":
            rule = K.run_rule(bars, qp, row.s, row.f, limits=LIM, costs=c)
            xr = K.run_yardstick(bars, x, row.f, limits=LIM, costs=c)
            v = K.ride_v(K.down_day(rule["ret"].to_numpy()[1:]), K.down_day(xr["ret"].to_numpy()[1:]))
            target = K.equal_calm_share(x, v, row.f, LIM)["share"]
        else:
            target = {"N": row.s, "X": x}[row.kind]
        res = K.run_yardstick(bars, target, row.f, limits=LIM, costs=c)
    else:
        tg, sh = K.shifted_copy(K.copy_schedule(qp, row.s), row.u, len(bars), row.f)
        res = (
            K.ride_run(bars, tg, limits=LIM, costs=c)
            if row.kind == "copy"
            else K.run_yardstick(bars, K.matched_share(sh), row.f, limits=LIM, costs=c)
        )
    return K.run_measures(res, c, s=row.s, w=row.w)


def test_every_9th_run_is_rerun_from_scratch(dry_runs):
    runs = tables(dry_runs)["runs"]
    p = panels()
    costs = R.cost_models(None)
    checked = 0
    for row in runs.iloc[::9].itertuples():
        got = _rerun(row, p, costs)
        for key in R.MEASURES:
            a, b = got[key], getattr(row, key)
            assert (a == b) or (isinstance(a, float) and math.isnan(a) and math.isnan(b)), (row.run_id, key)
        checked += 1
    assert checked == math.ceil(len(runs) / 9) and {"rule", "N", "X", "X_eq", "copy", "copy_X"} <= set(
        runs.iloc[::9]["kind"]
    )


def _my_labels(cells):
    """Section 9.2-9.4 written out here: Holm over the cells' p_calm (1 for a setting that never steps), then the
    label order."""
    ps = {c["w"]: (1.0 if not c["steps"] else c["p_calm"]) for c in cells}
    order = sorted(ps, key=lambda w: ps[w])
    holm, ok = {}, True
    for j, w in enumerate(order):
        ok = ok and ps[w] < 0.05 / (len(order) - j)
        holm[w] = ok
    out = {}
    for c in cells:
        if not c["steps"]:
            out[c["w"]] = K.NOT_STEPPING
        elif c["p_rough"] < 0.05:
            out[c["w"]] = K.ROUGHER
        elif c["V"] < 0 and holm[c["w"]] and c["e1"] < 0.05:
            out[c["w"]] = K.BELOW_NOTICE if c["p_eq"] < 0.05 else K.CALMER
        elif c["p_eq"] < 0.05:
            out[c["w"]] = K.NO_DIFFERENCE
        else:
            out[c["w"]] = K.CANT_TELL
    return holm, out


def test_the_luck_control_and_the_labels_are_recomputed_from_the_series_and_the_copies(dry_runs):
    t = tables(dry_runs)
    runs, series, spans = t["runs"], t["series"], t["spans"]
    p = panels()
    masks = R.rowset_masks(p["KRAKEN"], H.year_returns(p["KRAKEN"]))
    ret = {(r.family, r.w, r.s, r.f, r.kind): np.asarray(r.ret)[1:] for r in series.itertuples()}
    idx_cache: dict[int, np.ndarray] = {}
    for (fam, rowset, s, f), part in spans.groupby(["family", "rowset", "s", "f"]):
        keep = masks[rowset] if fam == "KRAKEN 1x" else np.ones(len(p[R.FAMILY[fam].source]) - 1, dtype=bool)
        n = int(keep.sum())
        idx = idx_cache.setdefault(n, hand_resampler(n, R.FAST.resamples))
        cells = []
        for row in part.itertuples():
            a, b = ret[(fam, row.w, s, f, "rule")][keep], ret[(fam, row.w, s, f, "X")][keep]
            dd = lambda r: math.sqrt(math.fsum(min(v, 0.0) ** 2 for v in r.tolist()) / len(r))  # noqa: E731
            v = math.log(dd(a)) - math.log(dd(b))
            da, db = np.minimum(a, 0.0) ** 2, np.minimum(b, 0.0) ** 2
            vs = np.array([0.5 * (np.log(np.mean(da[i])) - np.log(np.mean(db[i]))) for i in idx])
            diff = np.log1p(a) - np.log1p(b)
            gs = np.array([365 * np.mean(diff[i]) for i in idx])
            bb = len(idx) + 1
            assert row.V == v and row.rows == n
            assert row.p_calm == (1 + (vs >= 0).sum()) / bb and row.p_rough == (1 + (vs <= 0).sum()) / bb
            assert row.p_eq == (1 + (vs <= math.log(0.9)).sum()) / bb
            assert row.cost_p == (1 + (gs >= -0.02).sum()) / bb and row.cost_flag == (row.cost_p < 0.05)
            assert row.V_lo == float(np.percentile(vs, 5)) and row.V_hi == float(np.percentile(vs, 95))
            cell_runs = runs[
                (runs["family"] == fam)
                & (runs["scope"] == "span")
                & (runs["w"] == row.w)
                & (runs["s"] == s)
                & (runs["f"] == f)
            ]
            rule = cell_runs[cell_runs["kind"] == "rule"].iloc[0]
            assert bool(rule["steps_back"]) == row.steps
            cell = {
                "w": row.w,
                "steps": row.steps,
                "p_calm": row.p_calm,
                "p_rough": row.p_rough,
                "p_eq": row.p_eq,
                "V": v,
            }
            if R.FAMILY[fam].copies:
                copies = cell_runs[cell_runs["kind"] == "copy"].sort_values("u")
                mixes = cell_runs[cell_runs["kind"] == "copy_X"].sort_values("u")
                assert (
                    copies["u"].tolist()
                    == T.guarded_offsets(R.CHECKS[(R.FAMILY[fam].source, R.FAMILY[fam].lookback)])[
                        ::64
                    ].tolist()
                )
                vu = []
                for u in copies["u"]:
                    ca = ret_of(runs, p, fam, row.w, s, f, u, "copy")[keep]
                    xa = ret_of(runs, p, fam, row.w, s, f, u, "copy_X")[keep]
                    vu.append(math.log(dd(ca)) - math.log(dd(xa)))
                assert copies[f"V[{rowset}]"].tolist() == vu
                assert mixes["share"].tolist() == [my_copy_x(p, fam, row.w, s, f, u) for u in copies["u"]]
                v0 = rule[f"V[{rowset}]"]
                assert v0 == v
                rank = (1 + sum(x <= v0 for x in vu)) / (1 + len(vu))
                assert row.e1_rank_p == rank and row.e1_holds == (rank < 0.05)
                cell["e1"] = rank
            cells.append((row, cell))
        if R.FAMILY[fam].copies:
            holm, labels = _my_labels([c for _, c in cells])
            for row, _ in cells:
                assert row.holm == holm[row.w] and row.label == labels[row.w], (fam, rowset, row.w)
        else:
            assert all(pd.isna(row.label) for row, _ in cells)  # parquet reads the nulls back as NaN


_RET_CACHE: dict = {}


def my_copy_x(p, fam, w, s, f, u):
    """Copy u's same-average share written out here (section 9.3): the rule's check q's rotated by u weeks, the rows
    before the first check at the switch-on q, averaged exactly over rows 0 .. n-2."""
    family = R.FAMILY[fam]
    panel = p[family.source]
    n = len(panel)
    q = my_q_path(panel, w, f, 0, n, family.lookback)
    checks = [t for t in range(1, n) if t >= family.lookback and panel.index[t].day_of_week == 0]
    qk = q[checks]
    share = np.empty(n)
    k = -1
    for t in range(n):
        if k + 1 < len(checks) and checks[k + 1] == t:
            k += 1
        share[t] = s * q[0] if k < 0 else s * qk[(k + int(u)) % len(checks)]
    return _exact_mean(share[:-1])


def ret_of(runs, p, fam, w, s, f, u, kind):
    """A copy's (or its mix's) returns, rebuilt (the series table holds the rule's and X's only)."""
    key = (fam, w, s, f, u, kind)
    if key not in _RET_CACHE:
        family = R.FAMILY[fam]
        panel = p[family.source]
        c = R.cost_models(None)[(family.cost, family.wallet)]
        qp = K.q_path(panel, w, f, lookback=family.lookback)
        tg, sh = K.shifted_copy(K.copy_schedule(qp, s), int(u), len(panel), f)
        res = (
            K.ride_run(panel, tg, limits=LIM, costs=c)
            if kind == "copy"
            else K.run_yardstick(panel, K.matched_share(sh), f, limits=LIM, costs=c)
        )
        _RET_CACHE[key] = res["ret"].to_numpy()[1:]
    return _RET_CACHE[key]


def _my_d1(runs, spans, family, rowset="all", windows=None):
    """Section 10's D1 written out here (one pool)."""
    win = runs[(runs["family"] == family) & (runs["scope"] == "window") & (runs["kind"] == "rule")]
    if windows is not None:
        win = win[win["window"].isin(windows)]
    lab = spans[(spans["family"] == family) & (spans["rowset"] == rowset)]
    n = win["window"].nunique()
    usable, calmer_all = [], {}
    for w in R.FAST.settings:
        ok, every = True, True
        for s, f in R.FAST.mixes:
            mine = win[(win["w"] == w) & (win["s"] == s) & (win["f"] == f)]
            label = lab[(lab["w"] == w) & (lab["s"] == s) & (lab["f"] == f)]["label"].iloc[0]
            ok = ok and 2 * int((mine["V_X"] < 0).sum()) >= n and label in (K.CALMER, K.CANT_TELL)
            ok = ok and float(np.median(mine["c_X"])) <= 2.0
            every = every and label == K.CALMER
        if ok:
            usable.append(w)
            calmer_all[w] = every
    if not usable:
        return K.NO_DEFAULT
    return max(usable, key=lambda w: (calmer_all[w], w))


def test_d1_d2_and_the_flags_are_recomputed(dry_runs):
    t = tables(dry_runs)
    runs, spans, d = t["runs"], t["spans"], t["decision"]
    for fam in ("KRAKEN 1x", "BINANCE 1x", "KRAKEN 2x"):
        assert d["D1"][fam]["default"] == _my_d1(runs, spans, fam)
    boom = d["boom"]
    returns = t["start"]["year_returns"]
    ranked = sorted((int(y) for y in returns), key=lambda y: (-returns[str(y)], y))
    assert (
        boom["without the best 1"]["years"] == ranked[:1]
        and boom["without the best 2"]["years"] == ranked[:2]
    )
    for name in ("without the best 1", "without the best 2"):
        kept = [k for k in R.FAST.windows["KRAKEN"] if not any(P.overlaps(k, y) for y in boom[name]["years"])]
        assert boom[name]["windows"] == kept and len(kept) < 12  # the fast grid: MISSING
    checks = d["D2"]["checks"]
    assert checks["boom: without the best 1"] == checks["boom: without the best 2"] == K.MISSING
    assert (
        checks["Binance"] == d["D1"]["BINANCE 1x"]["default"]
        and checks["2x costs"] == d["D1"]["KRAKEN 2x"]["default"]
    )
    head = d["D1"]["KRAKEN 1x"]["default"]
    order = ("boom: without the best 1", "boom: without the best 2", "Binance", "2x costs")
    moved = [n for n in order if checks[n] not in (head, K.MISSING)]
    missing = [n for n in order if checks[n] == K.MISSING]
    if moved:
        want = "NOT ROBUST (" + ", ".join(moved + [f"{n}: MISSING" for n in missing]) + ")"
    else:
        want = "MISSING (" + ", ".join(missing) + ")"
    assert d["D2"]["label"] == want
    assert d["headline"] == {"default": head, "label": d["D2"]["label"]}
    for flag in d["flags"]:
        row = spans[
            (spans["family"] == "KRAKEN 1x")
            & (spans["rowset"] == "all")
            & (spans["w"] == flag["w"])
            & (spans["s"] == flag["s"])
            & (spans["f"] == flag["f"])
        ].iloc[0]
        assert flag["cost_flag"] == row["cost_flag"]
        cell = runs[
            (runs["family"] == "KRAKEN 1x")
            & (runs["scope"] == "span")
            & (runs["w"] == flag["w"])
            & (runs["s"] == flag["s"])
            & (runs["f"] == flag["f"])
        ]
        by = {r.kind: r for r in cell.itertuples()}
        assert flag["same_calm_more_return"] == by["X_eq"].cagr - by["rule"].cagr
        assert len(flag["labels"]) == 9 + 4  # Kraken 1x's 9 rowsets, Binance, 2x, L7 and L28
    assert d["steps_check"]["groups"] > 0 and d["failed_runs"] == 0


def test_the_steps_do_not_depend_on_costs_the_wallet_or_s(dry_runs):
    runs = tables(dry_runs)["runs"]
    rules = runs[runs["kind"] == "rule"]
    for _, part in rules.groupby(["source", "lookback", "f", "w", "scope", "window"]):
        assert part["q_hash"].nunique() == 1 and part["step_hash"].nunique() == 1
    k1 = rules[(rules["family"] == "KRAKEN 1x")].set_index(["scope", "window", "w", "s", "f"])["q_hash"]
    k2 = rules[(rules["family"] == "KRAKEN 2x")].set_index(["scope", "window", "w", "s", "f"])["q_hash"]
    assert k1.equals(k2)


# ------------------------------------------------------------------------------------------------ stops and failures


def _stopped(out: Path, rule: str, text: str) -> dict:
    summary = read_json(out / "run0" / "summary.json")
    assert summary["stop"]["rule"] == rule and text in summary["stop"]["message"], summary["stop"]
    assert not (out / "tracked" / "decision.json").exists()
    return summary


def _changing_hashes():
    calls = {"n": 0}
    real = R.file_hashes

    def changing(config_dir=None):
        calls["n"] += 1
        got = real(config_dir)
        return got if calls["n"] == 1 else {**got, "uv.lock": "0" * 64}

    return changing


def _one_more_span():
    real = R.expected_counts

    def plus_one(grid):
        got = real(grid)
        got["families"]["KRAKEN 1x"]["spans"] += 1
        return got

    return plus_one


@pytest.mark.parametrize(
    "name, make, text",
    [
        ("independent_x", lambda: lambda share: K.matched_share(share) + 1e-12, "is not the recomputed mean"),
        ("file_hashes", _changing_hashes, "a hashed file changed during the run"),
        ("expected_counts", _one_more_span, "span runs, expected"),
    ],
)
def test_the_consistency_stops_fire(tmp_path, monkeypatch, clean_git, tiny, name, make, text):
    monkeypatch.setattr(R, name, make())
    out = tmp_path / name
    assert R.main(dry(out)) == 3
    _stopped(out, "5", text)


def test_copy_0_the_steps_and_the_window_checks_stop_the_run(tmp_path, monkeypatch, clean_git, tiny):
    real_schedule = K.copy_schedule
    with monkeypatch.context() as m:
        m.setattr(
            K, "copy_schedule", lambda qp, s: real_schedule(qp, s)._replace(head_share=s * qp.q_on * 0.5)
        )
        out = tmp_path / "copy0"
        assert R.main(dry(out)) == 3
        _stopped(out, "5", "copy 0 is not the rule")
    with monkeypatch.context() as m:
        seq = iter(range(10**6))
        m.setattr(K, "q_hash", lambda qp: str(next(seq)))
        monkeypatch.setattr(R, "FAST", R.Grid(**{**TINY.__dict__, "families": ("KRAKEN 1x", "KRAKEN 2x")}))
        out = tmp_path / "steps"
        assert R.main(dry(out)) == 3
        _stopped(out, "5", "depend on s, costs or the wallet")
    monkeypatch.setattr(R, "FAST", TINY)
    real_prepare = R.prepare
    with monkeypatch.context() as m:

        def bent(panels_, grid, returns):
            got = real_prepare(panels_, grid, returns)
            key = next(iter(got["full_q"]))
            q = got["full_q"][key].q.copy()
            q[100:] = 0.0
            got["full_q"][key] = got["full_q"][key]._replace(q=q)
            return got

        m.setattr(R, "prepare", bent)
        out = tmp_path / "window"
        assert R.main(dry(out)) == 3
        _stopped(out, "5", "its q differs from the full panel's")
    with monkeypatch.context() as m:
        m.setattr(
            K, "check_yardstick", lambda res, share, f: (_ for _ in ()).throw(K.ConsistencyError("bent"))
        )
        out = tmp_path / "yard"
        assert R.main(dry(out)) == 3
        _stopped(out, "5", "bent")


def test_a_failed_run_is_logged_the_grid_goes_on_and_its_pool_is_missing(
    tmp_path, monkeypatch, clean_git, tiny
):
    real = K.run_rule

    def flaky(bars, qp, s, f, **kw):
        if len(bars) < 1000:  # every window rule run
            raise RuntimeError("flaky engine")
        return real(bars, qp, s, f, **kw)

    monkeypatch.setattr(K, "run_rule", flaky)
    out = tmp_path / "out"
    assert R.main(dry(out)) == 0
    runs = pd.read_parquet(out / "run0" / "runs.parquet")
    failed = runs[runs["status"] == "failed"]
    assert set(failed["kind"]) == {"rule"} and (failed["scope"] == "window").all()
    assert failed["error"].str.contains("RuntimeError: flaky engine").all()
    assert (runs[runs["kind"] == "X_eq"]["scope"] == "window").sum() == (runs["status"] == R.NOT_RUN).sum()
    fails = pd.read_parquet(out / "run0" / "failures.parquet")
    assert len(fails) == len(failed) and fails["traceback"].str.contains("flaky engine").all()
    d = read_json(out / "run0" / "decision.json")
    assert d["D1"]["KRAKEN 1x"]["default"] == K.MISSING and d["failed_runs"] == len(failed)
    assert len(runs) == R.expected_counts(TINY)["total"]


@pytest.mark.parametrize("workers", [1, 2])
def test_a_stop_in_a_later_block_keeps_the_blocks_that_returned(
    tmp_path, monkeypatch, clean_git, tiny, workers
):
    real = R.independent_x
    monkeypatch.setattr(
        R, "independent_x", lambda share: real(share) + (len(share) > 1000) * 1e-9
    )  # spans only
    out = tmp_path / "out"
    assert R.main(dry(out, workers=workers)) == 3
    _stopped(out, "5", "is not the recomputed mean")
    kept = sorted(p.name for p in (out / "run0" / "blocks").glob("*.runs.parquet"))
    assert kept == ["window-KRAKEN_1x-00.runs.parquet"]
    assert len(pd.read_parquet(out / "run0" / "blocks" / kept[0])) == 4


def test_a_crash_is_recorded_and_raised(tmp_path, monkeypatch, clean_git, tiny):
    monkeypatch.setattr(R, "decide", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="boom"):
        R.main(dry(out))
    summary = read_json(out / "run0" / "summary.json")
    assert summary["status"].startswith("crashed: RuntimeError: boom") and "Traceback" in summary["traceback"]
    assert R.runlog_entries(out / "tracked" / "RUNLOG.jsonl")[-1]["event"] == "crashed"
    assert (out / "run0" / "runs.parquet").exists() and (out / "run0" / "spans.parquet").exists()


# ------------------------------------------------------------------------------------------------ A0


def test_a0_panels_by_hand():
    pg, sig = C.build_panels("PG", 3)
    assert pg.equals(T.garch_panel(200_003)) and sig is pg
    pr, _ = C.build_panels("PR", 0)
    want = R.synthetic_market(2190, seed=220_000, start="2017-01-02")["BTC"]
    assert pr.index.equals(T.train_grid()) and np.array_equal(
        pr[("BTC", "close")].to_numpy(), want["close"].to_numpy()
    )
    nw, _ = C.build_panels("NW", 1)
    assert nw.equals(T.random_walk_panel(230_001))
    ns, _ = C.build_panels("NS", 2)
    shuffled = C.shuffled_market(R.synthetic_market(2190, seed=240_002, start="2017-01-02"), seed=241_002)
    assert np.array_equal(ns[("ETH", "close")].to_numpy(), shuffled["ETH"]["close"].to_numpy())
    prices, schedule = C.build_panels("NC", 4)
    assert prices.equals(T.garch_panel(250_004)) and schedule.equals(T.garch_panel(260_004))
    second, _ = C.build_panels("PG", 3, second=True)
    assert second.equals(T.garch_panel(300_003))
    with pytest.raises(ValueError, match="unknown set"):
        C.build_panels("XX", 0)


def test_a0_s_seeds_are_disjoint_from_section_2_s_and_from_each_other():
    prior = set(C.PRIOR_STREAMS)
    for second in (False, True):
        seen: dict[int, str] = {}
        for name in C.SETS:
            for j in range(100):
                for stream in C.streams(name, j, second):
                    assert stream >= 200_000 and stream not in prior
                    assert seen.setdefault(stream, name) == name
        assert len(seen) == 100 * 7
    assert C.streams("PG", 0) == [210_000] and C.streams("NC", 99) == [260_099, 270_099]
    assert C.streams("NS", 5) == [240_005, 241_005] and C.streams("PR", 1, True) == [320_001]
    assert 10_000 + R.TIMING_PANEL not in {s for n in C.SETS for j in range(100) for s in C.streams(n, j)}


def test_a0_alarm_limits_and_the_panel_count():
    assert C.alarm_limits(100) == {"count": 10, "boundary": 30} and C.alarm_limits(80) == {
        "count": 8,
        "boundary": 24,
    }
    assert C.choose_panels({"100": 300.0, "80": 1.0}, False) == 100
    assert C.choose_panels({"100": 300.0001, "80": 300.0}, False) == 80
    with pytest.raises(R.Refusal, match="stop rule 7"):
        C.choose_panels({"100": 400.0, "80": 300.5}, False)
    assert C.choose_panels({"100": 1e9, "80": 1e9}, True) == 1


def _panel(name, j, default=K.NO_DEFAULT, label=K.CANT_TELL, e1=False, holm=False, v=0.0, star=None):
    return {
        "set": name,
        "j": j,
        "status": K.OK,
        "default": default,
        "by_w": {
            w: {
                "V": v,
                "label": label,
                "e1_holds": e1,
                "holm": holm,
                "V_star": star if star is not None else np.zeros(9),
            }
            for w in K.W_VALUES
        },
    }


def test_a0_s_alarms_at_their_boundaries():
    n = 100

    def results(at=None):
        out = []
        for name in C.SETS:
            for j in range(n):
                out.append(_panel(name, j, **(at or {}).get((name, j), {})))
        return out

    calm = {("NW", j): {"label": K.CALMER} for j in range(10)}
    assert "A0-1" not in C.summarize(results(calm), n, 9)["alarms"]
    calm[("NW", 10)] = {"label": K.CALMER}
    assert "A0-1" in C.summarize(results(calm), n, 9)["alarms"]
    dflt = {("NS", j): {"default": 0.10} for j in range(11)}
    got = C.summarize(results(dflt), n, 9)
    assert got["false_default"]["NS"] == 11 and "A0-2" in got["alarms"]
    e1 = {("NC", j): {"e1": True} for j in range(11)}
    got = C.summarize(results(e1), n, 9)
    assert got["e1_size"]["0.08"] == 11 and got["alarms"] == ["A0-3"]
    assert C.summarize(results(dict(list(e1.items())[:10])), n, 9)["alarms"] == []
    power = {("PG", j): {"label": K.CALMER, "e1": True, "holm": True, "default": 0.12} for j in range(9)}
    got = C.summarize(results(power), n, 9)
    assert (
        got["power"]["PG"]["calmer_any"] == 9
        and got["power"]["PG"]["default"]["0.12"] == 9
        and got["low_power"]
    )
    assert got["power"]["PG"]["labels"]["0.1"][K.CALMER] == 9 and got["alarms"] == []
    failed = results()
    failed[0] = {"set": "PG", "j": 0, "status": "failed"}
    assert C.summarize(failed, n, 9)["failed"]["PG"] == 1


def test_a0_s_boundary_check_by_hand():
    star = np.array(
        [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    )  # 9 resamples: (1 + count) / 10 < 0.05 never
    panels_ = [_panel("PG", j, v=v, star=star) for j, v in enumerate((0.0, 0.1, 0.2))]
    got = C.boundary_counts(panels_, 9)
    assert got == {"upper": 0, "lower": 0, "tests": 12}
    low = np.full(40, -1.0)  # every V* below V-bar: the "calmer" tail rejects, the other does not
    pan = [_panel("NW", j, v=0.0, star=low) for j in range(3)]
    assert C.boundary_counts(pan, 40) == {"upper": 4 * 3, "lower": 0, "tests": 12}
    pan[0]["by_w"][0.08]["V"] = None
    pan[1]["status"] = "failed"
    assert C.boundary_counts(pan, 40)["tests"] == 2 * 3  # w 0.08: no panel; the others: panels 0 and 2

    def pg_with(rejections: int) -> list[dict]:
        out = [_panel(name, j) for name in C.SETS for j in range(100)]
        for i in range(rejections):  # 4 w a panel: 30 tests = 7 panels and 2 w of the 8th
            out[i // 4]["by_w"][K.W_VALUES[i % 4]]["V_star"] = np.full(9, -1.0)
        return out

    assert C.summarize(pg_with(30), 100, 39)["boundary"]["PG"]["upper"] == 30
    assert C.summarize(pg_with(30), 100, 39)["alarms"] == []
    assert C.summarize(pg_with(31), 100, 39)["alarms"] == ["A0-4"]


def test_a0_runs_end_to_end_on_tiny_sizes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(R, "measure_throughput", lambda *a, **k: dict(TINY_TIMING))
    monkeypatch.setattr(C, "FAST_SIZES", C.Sizes(panels=1, resamples=60, copy_stride=128, windows=(0, 48)))
    out = tmp_path / "a0"
    code = C.main(["--out-dir", str(out), "--fast"])
    a0 = read_json(out / "a0.json")
    assert code == (3 if a0["summary"]["alarms"] else 0)
    assert a0["summary"]["panels"] == 1 and a0["failures"] == []
    rows = pd.read_parquet(out / "panels.parquet")
    assert len(rows) == 5 * 4 and set(rows["set"]) == set(C.SETS)
    C._init(
        {
            "sizes": C.FAST_SIZES,
            "limits": LIM,
            "costs": R.cost_models(None)[("1x", K.DEPOSIT)],
            "idx": K.index_set(2189, resamples=60),
            "second": False,
        }
    )
    pg = C.panel_result("PG", 0)
    prices, _ = C.build_panels("PG", 0)
    qp = K.q_path(prices, 0.08, 0.5)
    rule = K.run_rule(prices, qp, 0.5, 0.5, limits=LIM, costs=C._CTX["costs"])
    xr = K.run_yardstick(prices, K.matched_share(0.5 * qp.q), 0.5, limits=LIM, costs=C._CTX["costs"])
    assert pg["by_w"][0.08]["V"] == K.ride_v(
        K.down_day(rule["ret"].to_numpy()[1:]), K.down_day(xr["ret"].to_numpy()[1:])
    )
    assert rows[(rows["set"] == "PG") & (rows["w"] == 0.08)]["V"].iloc[0] == pg["by_w"][0.08]["V"]
    assert C.run_panel(("XX", 0))["status"] == "failed"
    assert C.main(["--out-dir", str(R.REPO / "a0")]) == 2 and "never writes into" in capsys.readouterr().err
    assert C.main(["--out-dir", str(tmp_path / "w"), "--fast", "--workers", "0"]) == 2
    assert not (R.REPO / "a0").exists()
