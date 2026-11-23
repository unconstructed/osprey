"""protect-gains V1, the single validate look (``research/protect-gains/run_validate.py``) against VALIDATE_PLAN.md
sections 3-8: the windows and the count, the test-window guard, the data stops, the one-look protocol, the start
guards, V-a, V-b, V-c and the verdict at their boundaries, no look-ahead in a window's runs, and every reported number
recomputed from the runs table.

SYNTHETIC data only: every look is a ``--synthetic`` dry run in ``tmp_path`` (the plan's grid once, a tiny grid put in
its place elsewhere), on synthetic bars through 2024-07-01; the real catalog loader is replaced by one that fails the
test if it is reached (except where a test hands it synthetic bars on purpose), and the git state is injected where a
test needs one. Real-data guards run against stand-ins for every folder a real look uses (TESTING.md #48).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_portfolio import ALL_COLUMNS, edit_steady_entry, tamper_from

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.external import HoldoutWindowError
from lab.data.panel import load_panel
from lab.runner import holdmix as H
from lab.runner import portfolio as pf
from lab.runner import protect as P
from lab.runner.reference import Costs
from lab.runner.steady import panel_hash

STUDY_DIR = Path(__file__).resolve().parents[1] / "research" / "protect-gains"
NAME = "protect_gains_validate"
if NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(NAME, STUDY_DIR / "run_validate.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[NAME] = _module
    _spec.loader.exec_module(_module)
V = sys.modules[NAME]
R = V.R  # run.py, loaded once as protect_gains_run

SEED = 7
CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
LIM = pf.risk_limits("steady")
CUT = pd.Timestamp("2024-07-01", tz="UTC")
CANDIDATE = "A10/30d counts"
TINY = V.Grid(
    sources=("KRAKEN", "BINANCE"),
    costs=("1x", "2x"),
    windows=("j0", "full"),
    mixes=((0.70, 0.75),),
    settings=("R", CANDIDATE),
    name="test-tiny",
)
EVENTS = ("validate look V1",)


def _refuse_real_bars(*args, **kwargs):
    raise AssertionError("a test reached the real catalog loader")


@pytest.fixture(autouse=True)
def no_real_bars(monkeypatch):
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)


@pytest.fixture
def tiny(monkeypatch):
    monkeypatch.setattr(V, "PLAN_GRID", TINY)


@pytest.fixture
def clean_git(monkeypatch):
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(CLEAN))


def dry(out: Path, *extra: str) -> list[str]:
    return ["--synthetic", str(SEED), "--out-dir", str(out), *extra]


def real_folders(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Stand-ins for results/protect-gains, data/catalog and this study's folder (the tracked RUNLOG and copies)."""
    out, cat, here = tmp_path / "results" / "protect-gains", tmp_path / "data" / "catalog", tmp_path / "here"
    monkeypatch.setattr(R, "DEFAULT_OUT", out)
    monkeypatch.setattr(R, "DEFAULT_CATALOG", cat)
    monkeypatch.setattr(R, "HERE", here)
    return out, cat, here


def real_args(out: Path, cat: Path, *extra: str) -> list[str]:
    return ["--out-dir", str(out), "--catalog-dir", str(cat), *extra]


def write_snapshot(cat: Path, bars_hash: str = R.BARS_SHA256, snapshot_id: str = R.SNAPSHOT_ID) -> None:
    cat.mkdir(parents=True, exist_ok=True)
    (cat / catalog.SNAPSHOT_FILE).write_text(
        json.dumps({"snapshot_id": snapshot_id, "bars_content_sha256": bars_hash})
    )


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def events(log: Path) -> list:
    return [e.get("event") for e in R.runlog_entries(log)]


def tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def panels(seed: int = SEED) -> dict[str, pd.DataFrame]:
    loader = V.synthetic_bar_loader(seed)
    return {s: load_panel(s, "1d", last_close=CUT, catalog_dir="unused", loader=loader) for s in H.SOURCES}


def spent(out: Path, kind: str, *, tracked: Path | None = None) -> dict:
    """The look is spent: look.json and its tracked copy say INCONCLUSIVE with the error, and the RUNLOG holds the
    start line and one INCONCLUSIVE event line; no validate_runs.csv."""
    tracked = out / "tracked" if tracked is None else tracked
    look = read_json(out / "validate" / "look.json")
    assert (look["outcome"], look["verdict"], look["headline"]) == ("INCONCLUSIVE",) * 3
    assert look["error"]["kind"] == kind, look["error"]
    assert (tracked / "validate_look.json").read_bytes() == (out / "validate" / "look.json").read_bytes()
    assert (out / "validate" / "STARTED").is_file() and not (tracked / "validate_runs.csv").exists()
    ev = events(tracked / "RUNLOG.jsonl")
    assert ev[0] == "validate look V1" and len(ev) == 2 and ev[1].startswith("validate look V1: INCONCLUSIVE")
    return look


# ------------------------------------------------------------------------------------- pinned values


def test_the_windows_and_the_full_span_by_hand_from_the_calendar():
    want = [
        ("j0", "2023-01-02", "2024-01-01", 365),
        ("j1", "2023-02-02", "2024-02-01", 365),
        ("j2", "2023-03-02", "2024-03-01", 366),  # holds 2024-02-29
        ("j3", "2023-04-02", "2024-04-01", 366),
        ("j4", "2023-05-02", "2024-05-01", 366),
        ("j5", "2023-06-02", "2024-06-01", 366),
        ("j6", "2023-07-02", "2024-07-01", 366),
        ("full", "2023-01-02", "2024-07-01", 547),
    ]
    got = V.windows()
    assert [w[0] for w in got] == [w[0] for w in want] == list(V.PLAN_GRID.windows)
    loaded = panels()
    for (label, a, z, n), (glabel, ga, gz) in zip(want, got, strict=True):
        assert (glabel, ga, gz) == (label, pd.Timestamp(a, tz="UTC"), pd.Timestamp(z, tz="UTC"))
        assert (gz - ga).days + 1 == n
        for source in H.SOURCES:
            assert len(H.window_slice(loaded[source], ga, gz)) == n
    assert got[-1][2] == CUT and V.CUT == CUT and V.VALIDATE_ROWS == 547 and V.LAST_TRAIN == R.LAST_CLOSE


def test_the_count_of_768_and_the_pinned_values():
    c = V.expected_count(V.PLAN_GRID)
    assert c == {"total": 768, "twelve_month": 672, "full_span": 96}
    assert c["twelve_month"] == 2 * 2 * 7 * 6 * 4 and c["full_span"] == 2 * 2 * 6 * 4
    assert V.expected_count(TINY) == {"total": 16, "twelve_month": 8, "full_span": 8}
    g = V.PLAN_GRID
    assert (g.sources, g.costs, g.mixes) == (("KRAKEN", "BINANCE"), ("1x", "2x"), P.MIXES)
    assert V.SETTINGS == {
        "R": None,
        "A10/30d counts": ("A", 0.10, "wait30", "counts"),
        "A10/30d separate": ("A", 0.10, "wait30", "separate"),
        "A10/trend counts": ("A", 0.10, "trend", "counts"),
    }
    assert g.settings[0] == "R" and V.CANDIDATE == CANDIDATE
    assert V.HEADLINE_POOL == ("KRAKEN", "1x") and V.ROBUSTNESS_POOLS == (("BINANCE", "1x"), ("KRAKEN", "2x"))
    assert (V.C_MAX, V.PERCENTILE, V.RESTOP_MAX) == (0.10, 90.0, 0.25)
    assert R.SNAPSHOT_ID == "1746a21b75683e76" and R.BARS_SHA256.startswith("08f5ca2c")
    assert R.PANEL_HASHES["KRAKEN"].startswith("355aabe2") and R.PANEL_HASHES["BINANCE"].startswith(
        "2c1a4257"
    )
    assert R.ROWS == {"KRAKEN": 2190, "BINANCE": 1963}
    plan = STUDY_DIR / "VALIDATE_PLAN.md"
    assert V.VALIDATE_PLAN == plan and V.VALIDATE_PLAN_SHA256 == hashlib.sha256(plan.read_bytes()).hexdigest()
    assert V.run_id("KRAKEN", "1x", "j3", 0.7, 0.75, "R") == "V1:KRAKEN:1x:j3:0.7:0.75:R:-:none:none"
    assert (
        V.run_id("BINANCE", "2x", "full", 0.3, 0.5, CANDIDATE)
        == "V1:BINANCE:2x:full:0.3:0.5:A:0.1:wait30:counts"
    )
    assert set(V.CSV_COLUMNS).isdisjoint(V.FORBIDDEN_CSV) and "sharpe" in V.FORBIDDEN_CSV


def test_the_hashed_files_and_the_config_hash_move_with_them():
    paths = V.frozen_paths()
    assert set(R.frozen_paths()) < set(paths) and paths == sorted(paths)
    assert (
        "research/protect-gains/VALIDATE_PLAN.md" in paths
        and "research/protect-gains/run_validate.py" in paths
    )
    hashes = V.file_hashes()
    assert (
        hashes["research/protect-gains/run_validate.py"]
        == hashlib.sha256((STUDY_DIR / "run_validate.py").read_bytes()).hexdigest()
    )
    base = V.config_hash(hashes)
    assert V.config_hash({**hashes, "research/protect-gains/VALIDATE_PLAN.md": "0" * 64}) != base
    assert V.pinned_values()["plan_sha256"] == V.VALIDATE_PLAN_SHA256


# ------------------------------------------------------------------------------------- the test-window guard


def test_the_loader_is_never_asked_past_the_last_validate_close_and_the_record_comes_first(
    tmp_path, monkeypatch, tiny
):
    out = tmp_path / "dry"
    seen = []
    real = V.synthetic_bar_loader

    def watching(seed):
        inner = real(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            seen.append(
                (
                    end,
                    (out / "validate" / "STARTED").is_file(),
                    (out / "validate" / "start.json").is_file(),
                    events(out / "tracked" / "RUNLOG.jsonl"),
                )
            )
            return inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)

        return loader

    monkeypatch.setattr(V, "synthetic_bar_loader", watching)
    assert V.main(dry(out)) == 0
    assert len(seen) == 4 and all(s == (CUT, True, True, ["validate look V1"]) for s in seen)
    start = read_json(out / "validate" / "start.json")
    for key in ("commit", "config_hash", "snapshot", "plan_sha256", "git", "interpretations", "windows"):
        assert key in start
    assert start["plan_sha256"] == V.VALIDATE_PLAN_SHA256 and start["config_hash"] == V.config_hash(
        V.file_hashes()
    )
    line = R.runlog_entries(out / "tracked" / "RUNLOG.jsonl")[0]
    assert {k: line[k] for k in ("script", "event", "data", "config_hash", "plan_sha256")} == {
        "script": "run_validate.py",
        "event": "validate look V1",
        "data": "synthetic",
        "config_hash": start["config_hash"],
        "plan_sha256": V.VALIDATE_PLAN_SHA256,
    }
    for source in H.SOURCES:
        rec = start["panels"][source]
        assert (rec["train_rows"], rec["validate_rows"]) == (R.ROWS[source], 547)
        assert rec["last_close"] == CUT.isoformat()


def _frame_to(last: str, naive: bool = False) -> pd.DataFrame:
    idx = pd.date_range("2024-06-28", last, freq="D", tz=None if naive else "UTC", name="ts")
    return pd.DataFrame({"close": np.ones(len(idx))}, index=idx)


def test_the_guarded_loader_by_hand():
    calls = []

    def inner(last, naive=False):
        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            calls.append(end)
            return _frame_to(last, naive)

        return loader

    for end in (CUT + pd.Timedelta(microseconds=1), CUT + pd.Timedelta(days=1), None, "2024-07-02"):
        with pytest.raises(HoldoutWindowError, match="reaches past"):
            V.guarded(inner("2024-07-01"))("BTC/USD.KRAKEN", "1d", end=end)
    assert calls == []  # refused before the inner loader is asked
    assert len(V.guarded(inner("2024-07-01"))("BTC/USD.KRAKEN", "1d", end=CUT)) == 4
    assert len(V.guarded(inner("2024-07-01", naive=True))("BTC/USD.KRAKEN", "1d", end="2024-07-01")) == 4
    for naive in (False, True):
        with pytest.raises(HoldoutWindowError, match="returned a close 2024-07-02"):
            V.guarded(inner("2024-07-02", naive))("BTC/USD.KRAKEN", "1d", end=CUT)
    empty = V.guarded(lambda *a, **k: pd.DataFrame())("BTC/USD.KRAKEN", "1d", end=CUT)
    assert empty.empty


def _leaky(close: str):
    original = V.synthetic_bar_loader

    def factory(seed):
        inner = original(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            extra = bars.iloc[[-1]].copy()
            stamp = pd.Timestamp(close)
            extra.index = pd.DatetimeIndex([stamp], name="ts").as_unit("us")
            if stamp.tzinfo is None:
                bars = bars.tz_localize(None)
            got = pd.concat([bars, extra])
            got.attrs = bars.attrs
            return got

        return loader

    return factory


@pytest.mark.parametrize("close", ["2024-07-02T00:00:00+00:00", "2024-07-02", "2025-01-01T00:00:00+00:00"])
def test_a_returned_bar_after_the_last_validate_close_stops_the_look(tmp_path, monkeypatch, tiny, close):
    monkeypatch.setattr(V, "synthetic_bar_loader", _leaky(close))
    monkeypatch.setattr(V, "block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 3
    look = spent(out, "test window")
    assert "report the incident" in look["error"]["message"] and close[:10] in look["error"]["message"]
    assert "panels" not in read_json(out / "validate" / "start.json")
    assert not (out / "validate" / "runs.parquet").exists() and look["runs_logged"] == 0


def test_a_panel_past_the_cut_is_refused_by_the_data_check():
    panel = panels()["KRAKEN"]
    extra = panel.iloc[[-1]].copy()
    extra.index = pd.DatetimeIndex([CUT + pd.Timedelta(days=1)], name="ts").as_unit("us")
    with pytest.raises(V.Stop, match="test window: KRAKEN: the panel holds a close 2024-07-02"):
        V.check_panel("KRAKEN", pd.concat([panel, extra]), synthetic=True)


# ------------------------------------------------------------------------------------- the data stops


def test_the_train_part_hash_and_rows_and_the_validate_rows_by_hand(monkeypatch):
    loaded = panels()
    for source in H.SOURCES:
        V.check_panel(source, loaded[source], synthetic=True)
        with pytest.raises(V.Stop, match="train part's panel hash"):
            V.check_panel(source, loaded[source], synthetic=False)
    hashes = {s: panel_hash(loaded[s].loc[: R.LAST_CLOSE]) for s in H.SOURCES}
    monkeypatch.setattr(R, "PANEL_HASHES", hashes)  # the synthetic train parts stand in for section 3's
    panel = loaded["KRAKEN"]
    V.check_panel("KRAKEN", panel, synthetic=False)
    later = panel.copy()
    later.loc[pd.Timestamp("2023-06-15", tz="UTC"), ("BTC", "volume")] *= (
        1.5  # a validate bar: train hash kept
    )
    V.check_panel("KRAKEN", later, synthetic=False)
    earlier = panel.copy()
    earlier.loc[pd.Timestamp("2023-01-01", tz="UTC"), ("BTC", "volume")] *= 1.5  # the last train bar
    with pytest.raises(V.Stop, match="data: KRAKEN: the train part's panel hash"):
        V.check_panel("KRAKEN", earlier, synthetic=False)
    with pytest.raises(V.Stop, match="the train part has 2189 rows, expected 2190"):
        V.check_panel("KRAKEN", panel.iloc[1:], synthetic=True)
    gone = panel.drop(pd.Timestamp("2024-02-29", tz="UTC"))
    with pytest.raises(V.Stop, match="the validate part: .* 546 closes, expected 547"):
        V.check_panel("KRAKEN", gone, synthetic=True)
    short = panel.loc[: pd.Timestamp("2024-06-30", tz="UTC")]
    with pytest.raises(V.Stop, match="the validate part"):
        V.check_panel("KRAKEN", short, synthetic=True)
    rec = V.data_record(panel)
    assert (rec["train_rows"], rec["validate_rows"], rec["train_hash"]) == (2190, 547, hashes["KRAKEN"])


def _reshaped(change):
    original = V.synthetic_bar_loader

    def factory(seed):
        inner = original(seed)

        def loader(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = inner(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            got = change(instrument, bars)
            got.attrs = bars.attrs
            return got

        return loader

    return factory


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda inst, bars: bars.iloc[1:] if "KRAKEN" in inst else bars,
            "KRAKEN: the train part has 2189 rows",
        ),
        (
            lambda inst, bars: bars.drop(pd.Timestamp("2023-09-09", tz="UTC")) if "BINANCE" in inst else bars,
            "BINANCE: the validate part",
        ),
        (lambda inst, bars: bars.iloc[::-1], "load_panel refused the KRAKEN bars"),
    ],
)
def test_a_train_or_validate_row_count_or_bad_bars_stop_the_look(
    tmp_path, monkeypatch, tiny, change, message
):
    monkeypatch.setattr(V, "synthetic_bar_loader", _reshaped(change))
    monkeypatch.setattr(V, "block", lambda *a: pytest.fail("a backtest ran"))
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 3
    look = spent(out, "data")
    assert message in look["error"]["message"]
    if "refused" not in message:  # the panels are recorded before the checks
        assert set(read_json(out / "validate" / "start.json")["panels"]) == {"KRAKEN", "BINANCE"}


def test_real_data_with_another_train_part_stops_the_look(tmp_path, monkeypatch, clean_git, tiny):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    write_snapshot(cat)
    monkeypatch.setattr(catalog, "load_bars", V.synthetic_bar_loader(SEED))  # on purpose: other bars
    monkeypatch.setattr(V, "block", lambda *a: pytest.fail("a backtest ran"))
    assert V.main(real_args(out, cat)) == 3
    look = spent(out, "data", tracked=here)
    assert "the train part's panel hash" in look["error"]["message"]
    assert look["start"]["snapshot"] == {"snapshot_id": R.SNAPSHOT_ID, "bars_content_sha256": R.BARS_SHA256}


@pytest.mark.parametrize(
    ("snap", "message"),
    [
        ({"bars_hash": "0" * 64}, "is not ('1746a21b75683e76'"),
        ({"snapshot_id": "other-id"}, "('other-id'"),
        (None, "cannot read"),
    ],
)
def test_the_snapshot_pins_stop_the_look_after_started(tmp_path, monkeypatch, clean_git, tiny, snap, message):
    """Section 3: any difference stops the look (INCONCLUSIVE, the look is spent). SNAPSHOT.json is metadata: the
    start record holds it, and no bar is read."""
    out, cat, here = real_folders(monkeypatch, tmp_path)
    if snap is not None:
        write_snapshot(cat, **snap)
    assert V.main(real_args(out, cat)) == 3
    look = spent(out, "data", tracked=here)
    assert message in look["error"]["message"]
    assert V.main(real_args(out, cat)) == 2  # spent
    V.check_snapshot({"snapshot_id": "x"}, synthetic=True)
    V.check_snapshot({"snapshot_id": R.SNAPSHOT_ID, "bars_content_sha256": R.BARS_SHA256}, synthetic=False)
    cat.mkdir(parents=True, exist_ok=True)
    (cat / catalog.SNAPSHOT_FILE).write_text("[1]")
    assert "not a JSON object" in V.read_snapshot(cat, synthetic=False)["error"]


# ------------------------------------------------------------------------------------- one look and the guards


def test_a_second_look_is_refused_by_the_runlog_the_folder_or_the_tracked_record(tmp_path, capsys, tiny):
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 0
    before = tree(out)
    assert V.main(dry(out)) == 2
    assert "already holds a validate look" in capsys.readouterr().err
    shutil.rmtree(out / "validate")  # the folder deleted: the RUNLOG still refuses
    assert V.main(dry(out)) == 2
    assert "already holds a validate look" in capsys.readouterr().err
    copy = tmp_path / "copy"  # a copied results folder (without validate/)
    shutil.copytree(out, copy)
    assert V.main(dry(copy)) == 2
    assert "already holds a validate look" in capsys.readouterr().err
    (out / "tracked" / "RUNLOG.jsonl").write_text("")  # the RUNLOG reverted: the tracked record refuses
    assert V.main(dry(out)) == 2
    assert "validate_look.json exists" in capsys.readouterr().err
    (out / "validate").mkdir()  # and the folder alone
    (out / "tracked" / "validate_look.json").unlink()
    assert V.main(dry(out)) == 2
    assert "validate exists" in capsys.readouterr().err
    assert set(tree(out)) <= set(before)  # nothing written by a refusal
    assert V.holds_a_look([{"event": "validate look V1: complete", "data": "real"}])
    assert not V.holds_a_look([{"script": "run.py", "run": 0}, {"event": "complete"}])


def test_a_crash_spends_the_look_and_keeps_the_runs(tmp_path, monkeypatch, tiny):
    def crash(*args, **kwargs):
        raise KeyError("boom")

    monkeypatch.setattr(V, "decide", crash)
    out = tmp_path / "dry"
    with pytest.raises(KeyError, match="boom"):
        V.main(dry(out))
    look = spent(out, "crash")
    assert "KeyError" in look["error"]["message"] and "Traceback" in look["error"]["traceback"]
    assert len(pd.read_parquet(out / "validate" / "runs.parquet")) == 16 == look["runs_logged"]
    monkeypatch.undo()
    assert V.main(dry(out)) == 2  # spent


def test_a_stop_keeps_the_blocks_that_returned(tmp_path, monkeypatch, tiny):
    real, calls = V.block, []

    def third_stops(ctx, source, cost, window):
        calls.append((source, cost, window))
        if len(calls) == 3:
            raise V.Stop("consistency", "a stand-in stop")
        return real(ctx, source, cost, window)

    monkeypatch.setattr(V, "block", third_stops)
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 3
    look = spent(out, "consistency")
    runs = pd.read_parquet(out / "validate" / "runs.parquet")
    assert len(runs) == 4 == look["runs_logged"] and set(runs["window"]) == {"j0", "full"}
    assert calls[:2] == [("KRAKEN", "1x", "j0"), ("KRAKEN", "1x", "full")]


def test_real_looks_use_the_pinned_folders_and_a_clean_tree_only(tmp_path, monkeypatch, capsys, tiny):
    out, cat, here = real_folders(monkeypatch, tmp_path)
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(DIRTY))
    assert V.main(real_args(out, cat)) == 2
    err = capsys.readouterr().err
    assert "the git tree is dirty" in err and "stray.txt" in err
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(CLEAN))
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in ("costs.yaml", "splits.yaml", "risk_levels.yaml"):
        shutil.copy(CONFIG_DIR / name, cfg / name)
    for args, what in (
        (real_args(tmp_path / "other", cat), "--out-dir"),
        (real_args(out, cat, "--config-dir", str(cfg)), "--config-dir"),
        (real_args(out, tmp_path / "cat2"), "--catalog-dir"),
    ):
        assert V.main(args) == 2
        assert what in capsys.readouterr().err
    assert not out.exists() and not here.exists()
    monkeypatch.setattr(R, "git_state", lambda repo=R.REPO: dict(DIRTY))
    assert V.main(dry(tmp_path / "dry")) == 0  # a dry run on a dirty tree runs and records the state
    assert read_json(tmp_path / "dry" / "validate" / "start.json")["git"] == DIRTY


def test_a_dry_run_never_writes_into_the_study_folder_or_the_repo(tmp_path, capsys, tiny):
    before = tree(STUDY_DIR)
    results = R.REPO / "results" / "protect-gains"
    existed = (results / "validate").exists()
    for bad in (results, results / "dry", STUDY_DIR / "dry", R.REPO / "dry-run"):
        assert V.main(dry(bad)) == 2
        assert "never writes into" in capsys.readouterr().err
        assert not bad.exists() or bad == results
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 0
    assert tree(STUDY_DIR) == before and (results / "validate").exists() == existed
    assert sorted(p.name for p in out.iterdir()) == ["tracked", "validate"]
    assert sorted(p.name for p in (out / "tracked").iterdir()) == [
        "RUNLOG.jsonl",
        "validate_look.json",
        "validate_runs.csv",
    ]
    assert sorted(p.name for p in (out / "validate").iterdir()) == [
        "STARTED",
        "look.json",
        "runs.parquet",
        "start.json",
        "stops.parquet",
    ]
    assert events(out / "tracked" / "RUNLOG.jsonl") == ["validate look V1", "validate look V1: complete"]


def test_an_edited_plan_or_limits_that_refuse_a_mix_are_refused_at_start(tmp_path, monkeypatch, capsys, tiny):
    plan = tmp_path / "VALIDATE_PLAN.md"
    plan.write_text((STUDY_DIR / "VALIDATE_PLAN.md").read_text() + "\nan edit\n")
    monkeypatch.setattr(V, "VALIDATE_PLAN", plan)
    assert V.main(dry(tmp_path / "a")) == 2
    assert "not the committed pre-registration" in capsys.readouterr().err and not (tmp_path / "a").exists()
    monkeypatch.undo()
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in ("costs.yaml", "splits.yaml", "risk_levels.yaml"):
        shutil.copy(CONFIG_DIR / name, cfg / name)
    edit_steady_entry(cfg, "max_coin_pct: 60", "max_coin_pct: 54")  # BTC 0.525 + h 0.02 > 0.54
    assert V.main(dry(tmp_path / "b", "--config-dir", str(cfg))) == 2
    assert "refuse a mix" in capsys.readouterr().err and not (tmp_path / "b").exists()


# ------------------------------------------------------------------------------------- consistency and failures


def test_a_tool_copy_that_differs_from_hold_mix_stops_the_look(tmp_path, monkeypatch, tiny):
    real = H.hold_mix

    def off(params, bars, costs=None):
        res = real(params, bars, costs)
        res.attrs["held"] = np.asarray([*res.attrs["held"], len(bars) - 2], dtype=np.int64)
        return res

    monkeypatch.setattr(H, "hold_mix", off)
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 3
    assert "the tool copy's held differs from hold_mix's" in spent(out, "consistency")["error"]["message"]


def test_a_brake_check_that_fails_stops_the_look(tmp_path, monkeypatch, tiny):
    def broken(res, signal):
        raise P.ConsistencyError("the re-running's stops differ (stand-in)")

    monkeypatch.setattr(P, "check_events", broken)
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 3
    assert (
        "V1:KRAKEN:1x:j0:0.7:0.75:A:0.1:wait30:counts: the re-running"
        in spent(out, "consistency")["error"]["message"]
    )


@pytest.mark.parametrize("what", ["lost", "twice", "hashed"])
def test_a_lost_or_repeated_run_or_a_changed_file_stops_the_look(tmp_path, monkeypatch, tiny, what):
    if what == "lost":
        real = V.block

        def lossy(*args):
            got = real(*args)
            return {**got, "runs": got["runs"][:-1]}

        monkeypatch.setattr(V, "block", lossy)
        message = "the look logged"
    elif what == "twice":
        monkeypatch.setattr(V, "run_id", lambda *args: "same")
        message = "two runs share a run id"
    else:
        real_hashes, calls = V.file_hashes, []

        def moving(config_dir=None):
            calls.append(1)
            got = real_hashes(config_dir)
            return got if len(calls) == 1 else {**got, "lab/runner/protect.py": "0" * 64}

        monkeypatch.setattr(V, "file_hashes", moving)
        message = "a hashed file changed during the look"
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 3
    assert message in spent(out, "consistency")["error"]["message"]


def test_a_failed_run_is_logged_the_look_goes_on_and_its_pool_is_missing(tmp_path, monkeypatch, tiny):
    real, brake_calls = P.protect, []

    def first_brake_fails(params, bars, costs=None, signal=None):
        if params.get("line") is not None:
            brake_calls.append(1)
            if len(brake_calls) == 1:  # the first block: Kraken 1x j0, the candidate
                raise RuntimeError("engine refused (stand-in)")
        return real(params, bars, costs, signal)

    monkeypatch.setattr(P, "protect", first_brake_fails)
    out = tmp_path / "dry"
    assert V.main(dry(out)) == 0
    look = read_json(out / "validate" / "look.json")
    assert (look["verdict"], look["headline"]) == ("MISSING", "MISSING; whipsaw MISSING")
    assert look["checks"]["reason"] == "a run in the pool failed"
    assert [f["run_id"] for f in look["failed_runs"]] == ["V1:KRAKEN:1x:j0:0.7:0.75:A:0.1:wait30:counts"]
    assert "RuntimeError: engine refused" in look["failed_runs"][0]["traceback"]
    runs = pd.read_parquet(out / "validate" / "runs.parquet")
    bad = runs[runs["status"] != "ok"]
    assert len(runs) == 16 and bad["run_id"].tolist() == [look["failed_runs"][0]["run_id"]]
    assert bad["error"].iloc[0] == "RuntimeError: engine refused (stand-in)" and math.isnan(bad["F"].iloc[0])
    assert look["robustness"]["BINANCE 1x"]["verdict"] != "MISSING"
    assert look["robustness"]["BINANCE 1x"]["label"] == "differs"


def test_two_dry_runs_give_the_same_tables(tmp_path, tiny):
    for name in ("a", "b"):
        assert V.main(dry(tmp_path / name)) == 0
    a, b = (tmp_path / n / "tracked" / "validate_runs.csv" for n in ("a", "b"))
    assert a.read_bytes() == b.read_bytes()
    for table in ("runs", "stops"):
        x, y = (pd.read_parquet(tmp_path / n / "validate" / f"{table}.parquet") for n in ("a", "b"))
        pd.testing.assert_frame_equal(x, y)


# ------------------------------------------------------------------------------------- the checks by hand


def hand_table(rows: list[dict]) -> pd.DataFrame:
    """A runs table from hand rows (each: setting, s, window, and the numbers it sets)."""
    base = {
        "setting": "R",
        "s": 0.5,
        "window": "j0",
        "source": "KRAKEN",
        "cost": "1x",
        "f": 0.5,
        "status": "ok",
        "C": 0.0,
        "F": 0.1,
        "buybacks": 0,
        "restops": 0,
        "fired": False,
        "stops": 0,
        "usdc_share": 0.0,
        "overshoot_max": math.nan,
        "fees_pct_per_year_brake": 0.0,
    }
    return pd.DataFrame([{**base, **r} for r in rows], columns=list(base))


def pool(cand: dict[str, list], ref_f: list[float]) -> pd.DataFrame:
    """R's runs with F = ``ref_f`` and the candidate's with the columns of ``cand``, one per window j0, j1, ..."""
    n = len(ref_f)
    rows = [{"setting": "R", "s": 0.5, "window": f"j{j}", "F": ref_f[j]} for j in range(n)]
    for j in range(n):
        rows.append({"setting": CANDIDATE, "s": 0.5, "window": f"j{j}", **{k: v[j] for k, v in cand.items()}})
    return hand_table(rows)


def check(table: pd.DataFrame) -> dict:
    return V.pool_checks(table, "KRAKEN", "1x")


def test_v_a_passes_at_a_median_of_exactly_0_10():
    up = math.nextafter(0.10, 1.0)
    ref = [0.3, 0.3, 0.3]
    assert check(pool({"C": [0.0, 0.10, 0.2], "F": ref}, ref))["V-a"] == "PASS"
    assert check(pool({"C": [0.0, up, 0.2], "F": ref}, ref))["V-a"] == "FAIL"
    assert check(pool({"C": [-1.0, 0.10, 5.0], "F": ref}, ref))["C_med"] == 0.10
    four = pool({"C": [0.0, 0.0, 0.2, 0.3], "F": [0.3] * 4}, [0.3] * 4)  # even: the mean of the middle two
    assert check(four)["C_med"] == 0.10 and check(four)["V-a"] == "PASS"


def test_v_b_passes_at_equal_q_and_equal_worst_and_each_condition_fails_alone():
    ref = [0.1, 0.2, 0.3]  # Q0 = 0.2 + 0.8 * 0.1 = 0.28, worst 0.3
    same = check(pool({"F": [0.3, 0.1, 0.2]}, ref))
    assert (same["Q"], same["worst_F"], same["V-b"]) == (same["Q0"], same["worst_F0"], "PASS")
    by_q = check(pool({"F": [0.1, 0.25, 0.3]}, ref))  # Q = 0.29 > 0.28, worst equal
    assert by_q["worst_F"] == by_q["worst_F0"] and by_q["Q"] > by_q["Q0"] and by_q["V-b"] == "FAIL"
    by_worst = check(pool({"F": [0.0, 0.0, 0.31]}, ref))  # Q = 0.248 < 0.28, worst 0.31 > 0.3
    assert by_worst["Q"] < by_worst["Q0"] and by_worst["V-b"] == "FAIL"
    ulp = check(pool({"F": [0.1, 0.2, math.nextafter(0.3, 1.0)]}, ref))
    assert ulp["V-b"] == "FAIL"
    assert check(pool({"F": [0.0, 0.0, 0.0]}, ref))["V-b"] == "PASS"


def test_v_c_passes_at_exactly_25_percent_and_fails_with_no_buy_back():
    ref = [0.3, 0.3]
    at = check(pool({"buybacks": [3, 1], "restops": [1, 0], "F": ref}, ref))
    assert (at["restop_share"], at["V-c"]) == (0.25, "PASS")
    over = check(pool({"buybacks": [4, 3], "restops": [1, 1], "F": ref}, ref))
    assert over["restop_share"] == 2 / 7 and over["V-c"] == "FAIL"
    none = check(pool({"buybacks": [0, 0], "restops": [0, 0], "F": ref}, ref))
    assert (none["restop_share"], none["V-c"], none["verdict"]) == ("MISSING", "FAIL", "HOLDS UP")
    assert none["headline"] == "HOLDS UP; whipsaw FAIL"  # V-c never moves the verdict


def test_the_verdict_and_missing_by_hand():
    ref = [0.2, 0.3]
    holds = check(pool({"C": [0.0, 0.1], "F": ref, "buybacks": [1, 0]}, ref))
    assert (holds["verdict"], holds["headline"]) == ("HOLDS UP", "HOLDS UP; whipsaw PASS")
    assert check(pool({"C": [0.2, 0.2], "F": ref}, ref))["verdict"] == "DOES NOT HOLD UP"  # V-a alone
    assert check(pool({"C": [0.0, 0.0], "F": [0.2, 0.4]}, ref))["verdict"] == "DOES NOT HOLD UP"  # V-b alone
    for who in (CANDIDATE, "R"):
        table = pool({"C": [0.0, 0.0], "F": ref}, ref)
        table.loc[(table["setting"] == who).to_numpy().nonzero()[0][0], "status"] = "failed"
        got = check(table)
        assert [got[k] for k in ("V-a", "V-b", "V-c", "verdict")] == ["MISSING"] * 4
        assert got["headline"] == "MISSING; whipsaw MISSING"
    empty = check(pool({}, []))
    assert (empty["verdict"], empty["reason"]) == ("MISSING", "no runs in the pool")
    mismatched = pool({"C": [0.0, 0.0], "F": ref}, ref)
    mismatched.loc[mismatched["setting"] == CANDIDATE, "window"] = ["j0", "j5"]
    with pytest.raises(ValueError, match="same \\(mix, window\\) pairs"):
        check(mismatched)
    ahead = check(pool({"C": [-0.01, 0.0], "F": ref, "fired": [True, False]}, ref))
    assert (ahead["ahead_share"], ahead["fire_rate"]) == (0.5, 0.5)


def test_the_full_span_never_enters_a_pool_and_the_robustness_labels_by_hand():
    rows = []
    for source, cost, c in (("KRAKEN", "1x", 0.0), ("BINANCE", "1x", 0.0), ("KRAKEN", "2x", 0.5)):
        for window in ("j0", "j1", "full"):
            rows.append(
                {"source": source, "cost": cost, "setting": "R", "s": 0.5, "window": window, "F": 0.3}
            )
            cc = 9.0 if window == "full" else c  # the full span would fail V-a if it entered a pool
            rows.append(
                {"source": source, "cost": cost, "setting": CANDIDATE, "s": 0.5, "window": window, "C": cc}
            )
    table = hand_table(rows)
    table["f"] = 0.5
    stops = pd.DataFrame(columns=["source", "cost", "setting", *V.STOP_SUMMARY])
    got = V.decide(
        table,
        stops,
        V.Grid(("KRAKEN", "BINANCE"), ("1x", "2x"), ("j0", "j1", "full"), ((0.5, 0.5),), ("R", CANDIDATE)),
    )
    assert got["headline"] == "HOLDS UP; whipsaw FAIL" and got["checks"]["runs"] == 2
    assert got["robustness"]["BINANCE 1x"]["label"] == "same"
    assert got["robustness"]["KRAKEN 2x"]["label"] == "differs"
    assert got["robustness"]["KRAKEN 2x"]["headline"] == "DOES NOT HOLD UP; whipsaw FAIL"
    assert len(got["full_span"]) == 6
    assert {r["C"] for r in got["full_span"] if r["setting"] == CANDIDATE} == {9.0}


# ------------------------------------------------------------------------------------- no look-ahead


def test_no_look_ahead_in_a_window_s_runs():
    """Tamper the future on the whole panel (every field of both coins from ``cut`` on, the fill open of ``cut`` kept):
    for each run of window j3 through the script's own ``block``, every result row, order, stop and buy-back decided
    before ``cut`` is the same; the cuts land at every stop, buy-back and held close of the window's brake runs and
    the close after each, and at a few fixed rows."""
    loaded = panels()
    grid = V.Grid(("KRAKEN",), ("1x",), ("j3",), ((0.70, 0.75),), tuple(V.SETTINGS))
    costs = {"1x": Costs.from_yaml(capital_usd=5000.0)}

    def run(panel):
        results = {}
        real = P.protect

        def keep(params, bars, costs=None, signal=None):
            res = real(params, bars, costs, signal)
            results.setdefault((params["mode"], params["reading"]) if "mode" in params else "R", res)
            return res

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(P, "protect", keep)
            ctx = V.make_context(grid, {"KRAKEN": panel}, LIM, costs, "synthetic", "0" * 40)
            got = V.block(ctx, "KRAKEN", "1x", "j3")
        return got, results, ctx

    base, results, ctx = run(loaded["KRAKEN"])
    first = loaded["KRAKEN"].index.get_loc(ctx["windows"]["j3"][0])
    anchors = {
        int(t) + d
        for key, res in results.items()
        if key != "R"
        for t in (*res.attrs["stops"], *res.attrs["buybacks"], *res.attrs["buyback_held"])
        for d in (0, 1)
    }
    assert len(anchors) >= 4, "the window's brake runs should stop and buy back"
    for i, rel in enumerate(sorted(anchors | {1, 100, 250, 364})):
        cut = first + rel
        tampered = tamper_from(loaded["KRAKEN"], cut, i)
        other, res_b, ctx_b = run(tampered)
        for key, a in results.items():
            b = res_b[key]
            np.testing.assert_array_equal(
                a[ALL_COLUMNS].to_numpy()[:rel], b[ALL_COLUMNS].to_numpy()[:rel], err_msg=str(key)
            )
            for attr in ("orders", "stops", "buybacks", "buyback_held"):
                if attr in a.attrs:
                    x, y = np.asarray(a.attrs[attr]), np.asarray(b.attrs[attr])
                    np.testing.assert_array_equal(x[x < rel], y[y < rel], err_msg=f"{key} {attr}")
        moved = results["R"]["ret"].to_numpy()[rel:], res_b["R"]["ret"].to_numpy()[rel:]
        assert not np.array_equal(*moved)  # the tamper reaches the window's later rows
        keep = ("run_id", "stop", "stop_ts", "high", "line_value", "v_stop", "v_sale", "overshoot")
        sa = [{k: r[k] for k in keep} for r in base["stops"] if r["stop"] + 1 < rel]
        sb = [{k: r[k] for k in keep} for r in other["stops"] if r["stop"] + 1 < rel]
        assert sa == sb
        sig_a, sig_b = ctx["signals"][("KRAKEN", 0.75)], ctx_b["signals"][("KRAKEN", 0.75)]
        np.testing.assert_array_equal(
            sig_a[["I", "sma"]].to_numpy()[:cut], sig_b[["I", "sma"]].to_numpy()[:cut]
        )


# ------------------------------------------------------------------------------------- the plan's dry run


@pytest.fixture(scope="module")
def looked(tmp_path_factory):
    """The look on the plan's grid (768 runs), synthetic seed 7."""
    root = tmp_path_factory.mktemp("looked")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        assert V.main(dry(root)) == 0
    return {
        "runs": pd.read_parquet(root / "validate" / "runs.parquet"),
        "stops": pd.read_parquet(root / "validate" / "stops.parquet"),
        "look": read_json(root / "validate" / "look.json"),
        "tracked": read_json(root / "tracked" / "validate_look.json"),
        "csv": pd.read_csv(root / "tracked" / "validate_runs.csv"),
        "root": root,
    }


def plan_ids() -> set[str]:
    """Every run id section 5 asks for, from the plan's rules (not from the script's loops)."""
    tails = ("R:-:none:none", "A:0.1:wait30:counts", "A:0.1:wait30:separate", "A:0.1:trend:counts")
    windows = [f"j{j}" for j in range(7)] + ["full"]
    return {
        f"V1:{source}:{cost}:{w}:{s:g}:{f:g}:{tail}"
        for source in ("KRAKEN", "BINANCE")
        for cost in ("1x", "2x")
        for w in windows
        for s in (0.30, 0.50, 0.70)
        for f in (0.50, 0.75)
        for tail in tails
    }


def test_every_run_is_logged_and_each_run_s_numbers_come_from_its_configuration(looked):
    runs, stops, look = looked["runs"], looked["stops"], looked["look"]
    assert set(runs["run_id"]) == plan_ids() and len(runs) == 768 and (runs["status"] == "ok").all()
    assert look["counts"] == {
        "got": {"total": 768, "twelve_month": 672, "full_span": 96},
        "expected": {"total": 768, "twelve_month": 672, "full_span": 96},
    }
    assert (
        look["failed_runs"] == []
        and (looked["root"] / "tracked" / "validate_look.json").read_bytes()
        == (looked["root"] / "validate" / "look.json").read_bytes()
    )
    loaded = panels()
    costs = {"1x": Costs.from_yaml(capital_usd=5000.0)}
    costs["2x"] = costs["1x"].stressed(2.0)
    month0 = pd.Timestamp("2023-01-01", tz="UTC")
    bounds = {
        f"j{j}": (month0 + pd.DateOffset(months=j, days=1), month0 + pd.DateOffset(months=j + 12))
        for j in range(7)
    }
    bounds["full"] = (pd.Timestamp("2023-01-02", tz="UTC"), CUT)
    for i, row in enumerate(runs.itertuples(index=False)):
        if i % 9:
            continue
        first, last = bounds[row.window]
        piece = loaded[row.source].loc[first:last]
        assert (row.first_close, row.last_close, row.rows) == (first, last, len(piece)) and len(piece) == (
            last - first
        ).days + 1
        signal = P.index_signal(loaded[row.source], row.f).loc[piece.index]
        tp = P.tool_params(H.mix_targets(row.s, row.f), LIM)
        brake = row.line != "R"
        params = (
            {**tp, "line": row.line, "level": row.level, "mode": row.mode, "reading": row.reading}
            if brake
            else tp
        )
        res = P.protect(params, piece, costs[row.cost], signal if brake else None)
        measures, srows = P.run_measures(res, piece, costs[row.cost], signal if brake else None)
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
        ref = runs[(runs["run_id"] == row.run_id.rsplit(":", 4)[0] + ":R:-:none:none")]
        assert row.C == (1.0 - measures["v_end"] / float(ref["v_end"].iloc[0]) if brake else 0.0)
        mine = stops[stops["run_id"] == row.run_id]
        assert mine["stop"].tolist() == [r["stop"] for r in srows]
        assert mine["overshoot"].tolist() == [r["overshoot"] for r in srows]
    assert (stops["setting"] != "R").all() and set(stops["run_id"]) <= set(
        runs.loc[runs["stops"] > 0, "run_id"]
    )
    assert len(stops) == int(runs["stops"].sum())


def _mine(runs, source, cost, setting, mix=None):
    """An independent statement of section 6 (sharing no code with run_validate.py's rules)."""

    def sel(name):
        rows = runs[
            (runs["source"] == source)
            & (runs["cost"] == cost)
            & (runs["setting"] == name)
            & (runs["window"] != "full")
        ]
        if mix is not None:
            rows = rows[(rows["s"] == mix[0]) & (rows["f"] == mix[1])]
        return rows.sort_values(["s", "f", "window"])

    cand, ref = sel(setting), sel("R")
    assert list(zip(cand["s"], cand["f"], cand["window"], strict=True)) == list(
        zip(ref["s"], ref["f"], ref["window"], strict=True)
    )
    c = sorted(cand["C"].tolist())
    n = len(c)
    med = c[n // 2] if n % 2 else (c[n // 2 - 1] + c[n // 2]) / 2

    def p90(values):
        v = sorted(values)
        pos = 0.9 * (len(v) - 1)
        lo = math.floor(pos)
        return v[lo] + (pos - lo) * (v[min(lo + 1, len(v) - 1)] - v[lo])

    q, q0 = p90(cand["F"].tolist()), p90(ref["F"].tolist())
    worst, worst0 = max(cand["F"]), max(ref["F"])
    bb, rs = int(cand["buybacks"].sum()), int(cand["restops"].sum())
    va = "PASS" if med <= 0.10 else "FAIL"
    vb = "PASS" if q <= q0 and worst <= worst0 else "FAIL"
    vc = "PASS" if bb and rs / bb <= 0.25 else "FAIL"
    verdict = "HOLDS UP" if (va, vb) == ("PASS", "PASS") else "DOES NOT HOLD UP"
    return {
        "runs": n,
        "C_med": med,
        "C_mean": sum(c) / n,
        "Q": q,
        "Q0": q0,
        "worst_F": worst,
        "worst_F0": worst0,
        "buybacks": bb,
        "restops": rs,
        "V-a": va,
        "V-b": vb,
        "V-c": vc,
        "verdict": verdict,
        "headline": f"{verdict}; whipsaw {vc}",
        "ahead_share": sum(x < 0 for x in c) / n,
        "fire_rate": float(cand["fired"].mean()),
    }


def _same(mine: dict, theirs: dict) -> None:
    for key, value in mine.items():
        if isinstance(value, float):
            assert theirs[key] == pytest.approx(value, rel=1e-12, abs=1e-15), key
        else:
            assert theirs[key] == value, key


def test_every_reported_number_is_recomputed_from_the_runs_table(looked):
    runs, stops, look = looked["runs"], looked["stops"], looked["look"]
    pools = {"KRAKEN 1x": ("KRAKEN", "1x"), "BINANCE 1x": ("BINANCE", "1x"), "KRAKEN 2x": ("KRAKEN", "2x")}
    head = _mine(runs, "KRAKEN", "1x", CANDIDATE)
    assert head["runs"] == 42
    _same(head, look["checks"])
    assert (look["verdict"], look["whipsaw"], look["headline"], look["outcome"]) == (
        head["verdict"],
        head["V-c"],
        head["headline"],
        head["verdict"],
    )
    for name in ("BINANCE 1x", "KRAKEN 2x"):
        mine = _mine(runs, *pools[name], CANDIDATE)
        _same(mine, look["robustness"][name])
        assert look["robustness"][name]["label"] == (
            "same" if mine["headline"] == head["headline"] else "differs"
        )
    for name, (source, cost) in pools.items():
        for mix in P.MIXES:
            mine = _mine(runs, source, cost, CANDIDATE, mix)
            assert mine["runs"] == 7
            _same(mine, look["per_mix"][name][f"{mix[0]:g}/{mix[1]:g}"])
        for setting in ("A10/30d counts", "A10/30d separate", "A10/trend counts"):
            _same(_mine(runs, source, cost, setting), look["settings"][setting][name])
    full = runs[runs["window"] == "full"]
    assert len(look["full_span"]) == len(full) == 96
    for got, row in zip(look["full_span"], full.itertuples(index=False), strict=True):
        assert (got["source"], got["cost"], got["s"], got["f"], got["setting"]) == (
            row.source,
            row.cost,
            row.s,
            row.f,
            row.setting,
        )
        assert (got["F"], got["C"], got["stops"], got["buybacks"]) == (row.F, row.C, row.stops, row.buybacks)
    for name, (source, cost) in pools.items():
        mine = stops[(stops["source"] == source) & (stops["cost"] == cost) & (stops["setting"] == CANDIDATE)]
        got = look["stops"][name]
        assert len(got) == len(mine) and [g["overshoot"] for g in got] == mine["overshoot"].tolist()
        assert [g["stop_ts"] for g in got] == [t.isoformat() for t in mine["stop_ts"]]
    assert head["buybacks"] > 0 and look["stops"]["KRAKEN 1x"], "the synthetic look should exercise the brake"


def test_validate_runs_csv_is_one_row_per_run_with_no_return_column(looked):
    csv, runs = looked["csv"], looked["runs"]
    assert list(csv.columns) == list(V.CSV_COLUMNS) and len(csv) == len(runs) == 768
    for bad in ("sharpe", "total_return", "v_end", "b_kept_end"):
        assert bad not in csv.columns
    assert csv["run_id"].tolist() == runs["run_id"].tolist()
    np.testing.assert_allclose(csv["F"], runs["F"], rtol=1e-5)
    np.testing.assert_allclose(csv["C"], runs["C"], rtol=1e-5, atol=1e-12)
