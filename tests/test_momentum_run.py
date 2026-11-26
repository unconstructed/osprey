"""momentum-bold's run script (research/momentum-bold/run.py; PLAN.md sections 3-13). Synthetic data in tmp_path only:
the real loader and snapshot are stand-ins, and the real-data guards run against stand-in folders."""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lab.data.external import HoldoutWindowError
from lab.runner import momentum as M
from lab.search.study import load_trial_returns
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward

STUDY_DIR = Path(__file__).resolve().parents[1] / "research" / "momentum-bold"


def _load():
    if "momentum_bold_run" not in sys.modules:
        spec = importlib.util.spec_from_file_location("momentum_bold_run", STUDY_DIR / "run.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["momentum_bold_run"] = module
        spec.loader.exec_module(module)
    return sys.modules["momentum_bold_run"]


R = _load()
SNAP = {"snapshot_id": "bold-test", "sha256": "abc"}


@pytest.fixture(scope="module")
def dry(tmp_path_factory):
    out = tmp_path_factory.mktemp("dry") / "out"
    assert R.main(["--synthetic", "7", "--fast", "--out-dir", str(out)]) == 0
    run = out / "run0"
    return {
        "out": out,
        "run": run,
        "summary": json.loads((run / "summary.json").read_text()),
        "start": json.loads((run / "start.json").read_text()),
        "oos": pd.read_parquet(run / "oos.parquet"),
        "null": pd.read_parquet(run / "null.parquet"),
        "panel": R.load_train(R.synthetic_loader(7, R.FAST.coins), "synthetic"),
    }


def _sharpe(r) -> float:
    return stats.annualized_sharpe(np.asarray(r, dtype=float))


# ------------------------------------------------------------------------------------------------ the decided run


def test_the_dry_run_records_and_counts(dry):
    s, start = dry["summary"], dry["start"]
    assert s["status"] == "complete" and start["data"] == "synthetic" and start["fast"]
    assert set(p.name for p in dry["run"].iterdir()) == {"start.json", "summary.json", "oos.parquet", "null.parquet",
                                                          "folds.csv", "studies"}
    assert s["trials"]["raw"] == 4 * R.FAST.n_trials and s["trials"]["strict"] == 4 * R.FAST.n_trials + 5
    assert all(v == {"COMPLETE": R.FAST.n_trials} for v in s["trials"]["states"].values())
    assert s["panel"]["rows"] == len(dry["panel"]) == 1963 and s["panel"]["last"] == "2023-01-01T00:00:00+00:00"
    assert start["budget"] == 0.6 and start["costs"]["minor"]["pool_fee_bps"] == 10.0
    lines = [json.loads(x) for x in (dry["out"] / "tracked" / "RUNLOG.jsonl").read_text().splitlines()]
    assert [x["event"] for x in lines] == ["start", "end"]


def test_s_and_every_comparison_are_recomputed_from_their_inputs(dry):
    panel, oos, s = dry["panel"], dry["oos"], dry["summary"]
    n = len(panel)
    folds = walk_forward(n, n - 4 * 365, 365, expanding=True)
    chosen = R.chosen_params(pd.read_csv(dry["run"] / "folds.csv"))
    assert chosen == s["chosen"]
    costs = M.coin_costs()
    fn = partial(M.momentum, costs=costs)
    s_frame = M.stitch_frame(fn, chosen, panel, folds)
    assert np.array_equal(s_frame["ret"].to_numpy(), oos["S"].to_numpy())
    assert oos.index.equals(s_frame.index) and s_frame.index[0] == panel.index[n - 4 * 365 + 1]
    assert np.array_equal(M.stitch(partial(M.momentum, costs=costs.stressed(2.0)), chosen, panel, folds), oos["S_2x"])
    for i, (param, factor) in enumerate([("lookback", 0.8), ("lookback", 1.2), ("k", 0.8), ("k", 1.2)]):
        stepped = [{**p, param: max(1, math.floor(p[param] * factor + 0.5))} for p in chosen]
        assert np.array_equal(M.stitch(fn, stepped, panel, folds), oos[f"step{i}"])
    b1 = M.stitch(partial(M.hold_fixed, costs=costs), [{"weights": {"BTCUSDT": 1.0}, "every": None}] * 4, panel, folds)
    b2 = M.stitch(partial(M.hold_fixed, costs=costs), [{"weights": {"BTCUSDT": 0.5}, "every": 30}] * 4, panel, folds)
    b3 = M.stitch(partial(M.basket, costs=costs), [{}] * 4, panel, folds)
    for name, series in {"B1": b1, "B2": b2, "B3": b3}.items():
        assert np.array_equal(series, oos[name])
        assert s["numbers"]["bench"][name] == _sharpe(series)
    for col in oos.columns:
        assert s["sharpes"][col] == _sharpe(oos[col])
    d = s["described"]["S"]
    assert d["turnover_per_year"] == s_frame["turnover"].sum() * 365.0 / len(s_frame)
    assert d["forced"] == s_frame.attrs["forced"] and d["max_drawdown"] == mc.max_drawdown(oos["S"].to_numpy())
    assert d["total_return"] == pytest.approx(np.prod(1 + oos["S"]) - 1, rel=1e-12)
    for j in range(0, R.FAST.n_draws, 5):  # every 5th draw rerun from its seeds
        draw = [{**p, "seed": 10000 * (i + 1) + j} for i, p in enumerate(chosen)]
        assert np.array_equal(M.stitch(partial(M.random_select, costs=costs), draw, panel, folds), dry["null"][f"d{j:03d}"])


def test_e1_dsr_pbo_mc_regimes_gates_and_verdict_by_hand(dry):
    s, oos, panel = dry["summary"], dry["oos"], dry["panel"]
    sharpe = _sharpe(oos["S"])
    draws = [_sharpe(dry["null"][c]) for c in dry["null"].columns]
    rank_p = (1 + sum(d >= sharpe for d in draws)) / (len(draws) + 1)
    assert s["e1_rank"]["rank_p"] == rank_p and s["e1"] == ("HOLDS" if rank_p <= 0.05 else "FAILS")
    # The luck statistics from every logged trial's return file.
    sharpes, effs, pbos = [], [], []
    for study in s["studies"]:
        m = load_trial_returns(study, dry["run"] / "studies").dropna()
        sharpes += [stats.sharpe(m[c]) for c in m.columns]
        effs.append(stats.effective_trials(m.to_numpy()))
        pbos.append(stats.pbo(m.to_numpy(), n_blocks=10)["pbo"])
    r = oos["S"].to_numpy()
    assert len(sharpes) == s["trials"]["raw"]
    assert s["numbers"]["dsr_strict"] == stats.deflated_sharpe_ratio(r, sharpes, n_trials=len(sharpes) + 5)["dsr"]
    assert s["dsr_raw"] == stats.deflated_sharpe_ratio(r, sharpes, n_trials=len(sharpes))["dsr"]
    assert s["report"]["dsr_effective_count"] == stats.deflated_sharpe_ratio(r, sharpes, n_trials=float(np.sum(effs)))["dsr"]
    assert s["numbers"]["pbo"] == np.mean(pbos)
    p5 = np.percentile(mc.block_bootstrap_drawdowns(r, n_sims=1000, mean_block=20), 5)
    assert s["numbers"]["mc_p5"] == pytest.approx(p5, rel=1e-12)
    # G8: months by BTC's bar-day return, profit as log growth.
    btc = panel[("BTCUSDT", "close")]
    pos = btc.index.get_indexer(oos.index)
    ret = btc.to_numpy()[pos] / btc.to_numpy()[pos - 1] - 1
    months = (oos.index - pd.Timedelta(days=1)).strftime("%Y-%m")
    growth = pd.Series(1 + ret).groupby(np.asarray(months)).prod() - 1
    label = np.array(["bull" if growth[m] >= 0.1 else "bear" if growth[m] <= -0.1 else "sideways" for m in months])
    lr = np.log1p(r)
    total = math.fsum(lr)
    profit = {g: math.fsum(lr[label == g]) for g in ("bull", "bear", "sideways")}
    assert s["regimes"]["profit"] == pytest.approx(profit, rel=1e-12, abs=1e-15)
    regimes_pass = total > 0 and all(v <= total / 2 for v in profit.values())
    assert s["numbers"]["regimes_pass"] == regimes_pass
    nb = s["numbers"]
    steps = [_sharpe(oos[f"step{i}"]) for i in range(4)]
    gates = {
        "G1": sharpe >= 1.0,
        "G2": _sharpe(oos["S_2x"]) > 0.5,
        "G3": nb["dsr_strict"] >= 0.95,
        "G4": nb["pbo"] <= 0.25,
        "G5": sharpe > 0 and all(v >= 0.7 * sharpe for v in steps),
        "G6": nb["mc_p5"] >= -0.60,
        "G7": all(sharpe > _sharpe(oos[b]) for b in ("B1", "B2", "B3")),
        "G8": regimes_pass,
    }
    assert s["gates"] == {g: "PASS" if ok else "FAIL" for g, ok in gates.items()}
    failing = [g for g, ok in gates.items() if not ok] + ([] if rank_p <= 0.05 else ["E1"])
    assert s["failing"] == failing
    assert s["verdict"] == ("NOT A CANDIDATE" if failing else "CANDIDATE FOR AUDIT")


def test_the_dry_run_never_runs_twice_and_amendments_need_their_record(dry, tmp_path):
    assert R.main(["--synthetic", "7", "--fast", "--out-dir", str(dry["out"])]) == 2
    assert R.main(["--synthetic", "7", "--fast", "--out-dir", str(dry["out"]), "--amendment", "3"]) == 2
    assert R.main(["--synthetic", "7", "--fast", "--out-dir", str(tmp_path / "x"), "--amendment", "1"]) == 2
    assert not (tmp_path / "x").exists()


# ------------------------------------------------------------------------------------------------ guards


def _tree(path):
    """Every file and folder under ``path`` with its size and modification time, or None when it does not exist."""
    if not path.exists():
        return None
    return sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in path.rglob("*"))


def test_dry_runs_never_write_into_the_repo_or_the_study_folder(capsys):
    # results/momentum-bold/ exists once real run 0 has run (#82): nothing may be added or changed in it, and a
    # folder that did not exist must not be created
    for out in (R.REPO / "scratch", R.DEFAULT_OUT, R.DEFAULT_OUT / "dry"):
        before = _tree(out)
        assert R.main(["--synthetic", "1", "--fast", "--out-dir", str(out)]) == 2
        assert "never writes into" in capsys.readouterr().err
        assert R.main(["--time", "--fast", "--out-dir", str(out)]) == 2
        assert _tree(out) == before
    assert R.main(["--fast"]) == 2
    assert "--fast is for synthetic dry runs only" in capsys.readouterr().err


def test_time_writes_its_projection_to_a_scratch_folder(tmp_path):
    assert R.main(["--time", "--fast", "--out-dir", str(tmp_path)]) == 0
    t = json.loads((tmp_path / "time.json").read_text())
    assert t["backtests"] == 4 * (R.FAST.n_trials + 11 + R.FAST.n_draws)
    assert t["cpu_minutes"] == t["backtests"] * t["seconds_each"] / 60
    assert R.projection(R.PLAN_SIZES, 0.1)["backtests"] == 1084


def test_a_config_without_the_small_coin_multiplier_refuses(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in ("splits.yaml", "risk_levels.yaml"):
        (cfg / name).write_text((R.CONFIG_DIR / name).read_text())
    text = (R.CONFIG_DIR / "costs.yaml").read_text()
    (cfg / "costs.yaml").write_text("\n".join(x for x in text.splitlines() if "small_coin" not in x) + "\n")
    out = tmp_path / "out"
    assert R.main(["--synthetic", "1", "--fast", "--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert not out.exists()


@pytest.fixture
def real(tmp_path, monkeypatch):
    """Stand-ins for every folder a real run uses, a clean tree and the pinned snapshot; the real loader fails."""
    here, out, cat = tmp_path / "here", tmp_path / "results", tmp_path / "catalog"
    here.mkdir()
    (here / "PLAN.md").write_text("# plan\n")
    monkeypatch.setattr(R, "HERE", here)
    monkeypatch.setattr(R, "PLAN", here / "PLAN.md")
    monkeypatch.setattr(R, "DEFAULT_OUT", out)
    monkeypatch.setattr(R, "DEFAULT_CATALOG", cat)
    monkeypatch.setattr(R, "SNAPSHOT", SNAP)
    monkeypatch.setattr(R, "git_state", lambda: {"commit": "c0ffee", "dirty": False, "changes": []})
    monkeypatch.setattr(R, "real_snapshot", lambda catalog_dir: dict(SNAP))
    monkeypatch.setattr(R, "PLAN_SIZES", R.FAST)

    def no_loader(catalog_dir):
        raise AssertionError("the real loader must not be reached")

    monkeypatch.setattr(R, "real_loader", no_loader)
    return {"here": here, "out": out, "cat": cat, "tmp": tmp_path}


def test_real_run_start_guards(real, monkeypatch, capsys):
    def refused(argv, msg):
        assert R.main(argv) == 2
        assert msg in capsys.readouterr().err
        assert not real["out"].exists() and not (real["here"] / "RUNLOG.jsonl").exists()

    refused(["--out-dir", str(real["tmp"] / "other")], "a real run writes only to")
    refused(["--catalog-dir", str(real["tmp"] / "other")], "a real run reads only")
    refused(["--config-dir", str(real["tmp"])], "a real run reads config/ only")
    monkeypatch.setattr(R, "real_snapshot", lambda catalog_dir: {"snapshot_id": "x", "sha256": "other"})
    refused([], "is not the pinned")
    monkeypatch.setattr(R, "SNAPSHOT", None)
    refused([], "SNAPSHOT is not pinned")
    monkeypatch.setattr(R, "SNAPSHOT", SNAP)
    monkeypatch.setattr(R, "real_snapshot", lambda catalog_dir: dict(SNAP))
    refused(["--amendment", "1"], "run 0 has no start record")
    monkeypatch.setattr(R, "measure_timing", lambda sizes: {"backtests": 1, "seconds_each": 0.0, "cpu_minutes": 120.5})
    refused([], "(stop rule 7)")

    def broken(sizes):
        raise RuntimeError("no timing")

    monkeypatch.setattr(R, "measure_timing", broken)
    refused([], "the timing failed")
    monkeypatch.setattr(R, "git_state", lambda: {"commit": "c0ffee", "dirty": True, "changes": ["?? x"]})
    refused([], "the git tree is dirty")


def test_a_real_amendment_needs_its_plan_row(real):
    (real["out"] / "run0").mkdir(parents=True)
    (real["out"] / "run0" / "start.json").write_text("{}")
    assert R.main(["--amendment", "1"]) == 2
    assert not (real["out"] / "run1").exists()


def test_the_start_record_and_runlog_come_before_any_bar_and_only_train_bars_are_asked(real, monkeypatch):
    monkeypatch.setattr(R, "measure_timing", lambda sizes: {"backtests": 1, "seconds_each": 0.0, "cpu_minutes": 120.0})
    asked = []

    class Seen(Exception):
        pass

    def spy(end, catalog_dir=None):
        asked.append(end)
        start = json.loads((real["out"] / "run0" / "start.json").read_text())
        log = (real["here"] / "RUNLOG.jsonl").read_text()
        assert start["data"] == "real" and start["snapshot"] == SNAP and start["git"]["commit"] == "c0ffee"
        assert json.loads(log)["event"] == "start"
        raise Seen

    with pytest.raises(Seen):
        R.main([], loader=spy)
    assert asked == [pd.Timestamp("2023-01-01", tz="UTC")]
    summary = json.loads((real["out"] / "run0" / "summary.json").read_text())
    assert summary["status"] == "crashed" and "Seen" in summary["error"]
    assert [json.loads(x)["event"] for x in (real["here"] / "RUNLOG.jsonl").read_text().splitlines()] == [
        "start", "crashed"]
    assert R.main([]) == 2  # run 0 runs once


def _stopped(out: Path, rule: str):
    s = json.loads((out / "run0" / "summary.json").read_text())
    assert s["status"] == "stopped" and s["rule"] == rule and "verdict" not in s and "gates" not in s
    assert json.loads((out / "tracked" / "RUNLOG.jsonl").read_text().splitlines()[-1])["rule"] == rule


def test_a_close_after_the_train_window_is_stop_rule_3(tmp_path):
    def late(end, catalog_dir=None):
        return R.synthetic_loader(1, 4)(pd.Timestamp("2023-01-02", tz="UTC"))

    def refusing(end, catalog_dir=None):
        raise HoldoutWindowError("past the cut")

    for i, loader in enumerate((late, refusing)):
        out = tmp_path / f"o{i}"
        assert R.main(["--synthetic", "1", "--fast", "--out-dir", str(out)], loader=loader) == 3
        _stopped(out, "3")
    with pytest.raises(HoldoutWindowError):
        R.synthetic_loader(1, 4)(pd.Timestamp("2024-07-02", tz="UTC"))


def test_bad_bars_are_stop_rule_2(tmp_path):
    def gap(end, catalog_dir=None):
        f = R.synthetic_loader(1, 4)(end)
        f["BTCUSDT"] = f["BTCUSDT"].drop(f["BTCUSDT"].index[500])
        return f

    def nan(end, catalog_dir=None):
        f = R.synthetic_loader(1, 4)(end)
        f["ETHUSDT"].iloc[3, 0] = np.nan
        return f

    def short(end, catalog_dir=None):
        return {s: f.iloc[:-1] for s, f in R.synthetic_loader(1, 4)(end).items()}

    for i, loader in enumerate((gap, nan, short)):
        out = tmp_path / f"o{i}"
        assert R.main(["--synthetic", "1", "--fast", "--out-dir", str(out)], loader=loader) == 3
        _stopped(out, "2")


def test_the_consistency_stops_fire(tmp_path, monkeypatch):
    orig = M.stitch

    def off(*args, **kw):
        s = orig(*args, **kw)
        return s * (1 + 1e-15)

    monkeypatch.setattr(R.M, "stitch", off)
    out = tmp_path / "a"
    assert R.main(["--synthetic", "1", "--fast", "--out-dir", str(out)]) == 3
    _stopped(out, "5")
    monkeypatch.setattr(R.M, "stitch", orig)
    calls = []
    real_hashes = R.file_hashes

    def moving(config_dir):
        calls.append(1)
        h = real_hashes(config_dir)
        return h if len(calls) == 1 else {**h, "lab/runner/momentum.py": "changed"}

    monkeypatch.setattr(R, "file_hashes", moving)
    out = tmp_path / "b"
    assert R.main(["--synthetic", "1", "--fast", "--out-dir", str(out)]) == 3
    _stopped(out, "8")


def test_the_config_hash_covers_the_files_and_pinned_values(monkeypatch):
    paths = R.frozen_paths()
    for rel in ("lab/runner/momentum.py", "lab/runner/steady.py", "lab/search/walkforward.py", "lab/validation/stats.py",
                "lab/data/bold.py", "research/momentum-bold/run.py", "research/momentum-bold/PLAN.md",
                "config/costs.yaml", "config/risk_levels.yaml"):
        assert rel in paths
    hashes = R.file_hashes(None)
    base = R.config_hash(hashes)
    assert R.config_hash({**hashes, "config/costs.yaml": "x"}) != base
    monkeypatch.setattr(M, "HAIRCUT", 0.5)
    assert R.config_hash(hashes) != base


def test_git_state_counts_untracked_files(tmp_path):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x")
    assert R.git_state(tmp_path)["dirty"] is False
    (tmp_path / "new.py").write_text("x")
    assert R.git_state(tmp_path)["changes"] == ["?? new.py"]
    elsewhere = tmp_path.parent / f"{tmp_path.name}-not-a-repo"
    elsewhere.mkdir()
    with pytest.raises(RuntimeError, match="failed"):
        R.git_state(elsewhere)
