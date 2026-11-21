"""The rebalance-steady study scripts (``research/rebalance-steady/``: study.py, run_train.py, freeze.py,
run_validate.py) against PLAN.md sections 7-13 and amendment A4: the start guards, the start record, the hash
rules of stop rule 10 and its risk-levels exception, the look's guards and consistency checks, and the verdict
rules. SYNTHETIC data only: every run is a ``--synthetic --fast`` dry run in ``tmp_path``, with an injected git state
where the test needs one, and the real catalog loader is replaced by one that fails the test if it is ever reached.
"""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_portfolio import edit_steady_entry, set_steady_budget

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.external import HoldoutWindowError
from lab.runner import steady as sd
from lab.runner.reference import Costs
from lab.search.report import overfitting_report
from lab.search.study import SearchConfig, run_study
from lab.validation import montecarlo as mc
from lab.validation import stats
from lab.validation.splits import walk_forward

HERE = Path(__file__).resolve().parents[1] / "research" / "rebalance-steady"


def _load(name: str, file: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


RT = _load("rebalance_steady_run_train", "run_train.py")
FZ = _load("rebalance_steady_freeze", "freeze.py")
RV = _load("rebalance_steady_run_validate", "run_validate.py")
S = RT.S
CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
SEED = 7


def _refuse_real_bars(*args, **kwargs):
    raise AssertionError("a test reached the real catalog loader")


@pytest.fixture(autouse=True)
def no_real_bars(monkeypatch):
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)


@pytest.fixture
def clean_git(monkeypatch):
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))


def copy_config(dst: Path, src: Path = CONFIG_DIR) -> Path:
    dst.mkdir(parents=True)
    for name in ("costs.yaml", "splits.yaml", "risk_levels.yaml"):
        shutil.copy(src / name, dst / name)
    return dst


def edit_risk(cfg: Path, old: str, new: str) -> None:
    """Replace ``old`` (exactly once there) in the steady entry of ``cfg/risk_levels.yaml``, by key: never the
    first occurrence in the file, which is balanced's once Steady's budget is set (#55)."""
    edit_steady_entry(cfg, old, new)


def train_args(out: Path, cfg: Path, *extra: str) -> list[str]:
    return [
        "--synthetic",
        str(SEED),
        "--fast",
        "--out-dir",
        str(out),
        "--config-dir",
        str(cfg),
        "--catalog-dir",
        str(out.parent / "no-catalog"),
        *extra,
    ]


def validate_args(out: Path, cfg: Path, *extra: str, seed: int = SEED) -> list[str]:
    return [
        "--synthetic",
        str(seed),
        "--out-dir",
        str(out),
        "--config-dir",
        str(cfg),
        "--catalog-dir",
        str(out.parent / "no-catalog"),
        *extra,
    ]


def here_hashes() -> dict[str, str]:
    return {k: v for k, v in S.tree_hashes(HERE).items() if "__pycache__" not in k}


def summary(out: Path, k: int = 0) -> dict:
    return json.loads((out / "train" / f"run{k}" / "summary.json").read_text())


def set_look_due(out: Path, due: bool) -> None:
    """Stand in for the train verdict (the synthetic one is whatever the data give)."""
    path = out / "train" / "run0" / "summary.json"
    data = json.loads(path.read_text())
    data["results"]["train_verdict"] = {"verdict": "LOOK DUE" if due else "NO EDGE", "look_due": due}
    path.write_text(json.dumps(data))


def real_folders(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Stand-ins for the pinned real-data folders (results/rebalance-steady, data/catalog) in ``tmp_path``, so a
    real-data run can pass the path guard without touching the repo; the config folder stays config/. The study
    folder (``S.HERE``: the tracked RUNLOG.jsonl and committed copies) is a stand-in too, so a real run recorded in
    the repo's RUNLOG never decides which guard these tests reach (#48)."""
    out, catalog_dir = tmp_path / "results" / "rebalance-steady", tmp_path / "data" / "catalog"
    monkeypatch.setattr(S, "DEFAULT_OUT", out)
    monkeypatch.setattr(S, "DEFAULT_CATALOG", catalog_dir)
    monkeypatch.setattr(S, "HERE", tmp_path / "here")
    return out, catalog_dir


def write_start(out: Path, k: int, data: str, fast: bool, status: str = "started") -> None:
    """A run's summary.json with just enough of a start record for the amendment guards."""
    path = out / "train" / f"run{k}" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = {"data": data, "fast": fast, "risk_limits": {}}
    path.write_text(json.dumps({"run": k, "status": status, "start": start, "results": {}}))


@pytest.fixture(scope="module")
def train0(tmp_path_factory):
    """One ``run_train.py`` run 0 dry run (synthetic seed 7, fast settings, a copy of config/), clean git. Steady's
    budget is written as TBD in the copy, as rebalance-steady's real run 0 read it: the tests on this run and on
    its copies (``fresh``, ``frozen``) are about a run whose G6 is MISSING and the budget-only change after it, so
    they set that state up instead of reading the real file's budget (#55)."""
    root = tmp_path_factory.mktemp("rs_scripts")
    cfg = copy_config(root / "config")
    set_steady_budget(cfg, "TBD")
    out = root / "out"
    before = here_hashes()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        assert RT.main(train_args(out, cfg)) == 0
    return {"root": root, "out": out, "cfg": cfg, "before": before}


@pytest.fixture(scope="module")
def train0_budget(tmp_path_factory):
    """Run 0 again with a numeric drawdown budget (100%) in the copied risk_levels.yaml, so G6 is computed (not
    MISSING) and its wiring can be checked."""
    root = tmp_path_factory.mktemp("rs_budget")
    cfg = copy_config(root / "config")
    set_steady_budget(cfg, "100")  # by key, whatever the real file holds (#55)
    out = root / "out"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        assert RT.main(train_args(out, cfg)) == 0
    return {"root": root, "out": out, "cfg": cfg}


@pytest.fixture
def fresh(train0, tmp_path):
    """A private copy of run 0's output folder and config, to change freely."""
    out = tmp_path / "out"
    shutil.copytree(train0["out"], out)
    cfg = copy_config(tmp_path / "config", train0["cfg"])
    return out, cfg


@pytest.fixture
def frozen(fresh, clean_git):
    """A copy of run 0 whose train verdict calls for the look, frozen."""
    out, cfg = fresh
    set_look_due(out, True)
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    return out, cfg


# ----------------------------------------------------------------------------------- pure helpers


def _plan(rows: str, before: str = "", after: str = "") -> str:
    return f"## 13\n{before}**Amendments.** Dated.\n{rows}\n**Deviations.** Every departure.\n{after}"


def test_amendment_row_must_name_the_run():
    plan = _plan("- **Amendment run 1 (2026-12-01).** A bug.\n- **Amendment run 12** later\n")
    assert S.amendment_row_present(plan, 1)
    assert not S.amendment_row_present(plan, 2)
    assert not S.amendment_row_present(_plan("  - **Amendment run 1** indented\n"), 1)
    assert not S.amendment_row_present(_plan("- **Amendment run 12**\n"), 1)
    # only a row in the amendments list of section 13 counts (INTERPRETATIONS["amendment_row"])
    row = "- **Amendment run 1 (2026-12-01).** A bug.\n"
    assert not S.amendment_row_present(_plan("", before=row), 1)
    assert not S.amendment_row_present(_plan("", after=row), 1)
    assert not S.amendment_row_present(row, 1)  # no amendments list at all
    assert not S.amendment_row_present(f"**Deviations.**\n{row}**Amendments.**\n", 1)  # markers out of order
    # markers mentioned inside a row do not end the list; only the headings at the start of a line count
    mid = "- **A9.** Rows between **Amendments.** and **Deviations.** count.\n"
    assert S.amendment_row_present(_plan(mid + row), 1)
    # the real plan: no amendment run yet, and a row added at the end of its list is found
    text = S.PLAN.read_text()
    assert S.amendment_row_present(text, 1) is False
    head = "\n**Deviations.** Every departure"
    assert text.count(head) == 1
    assert S.amendment_row_present(text.replace(head, "\n" + row + head), 1)


def test_study_names_and_their_parse():
    assert S.study_tag(0, 0) == "rebalance-steady-s0"
    assert S.study_tag(1, 2) == "rebalance-steady-s1_a2"
    assert S.parse_study("rebalance-steady-s1_a2_wf03") == {"seed": 1, "run": 2, "part": "wf03"}
    assert S.parse_study("rebalance-steady-s0_final") == {"seed": 0, "run": 0, "part": "final"}
    assert S.parse_study("other") == {"seed": None, "run": None, "part": None}


def test_s_bins_by_hand():
    assert S.s_bin(0.2) == "[0.20, 0.30)"
    assert S.s_bin(0.3) == "[0.30, 0.40)"  # (0.3 - 0.2) / 0.1 < 1 in floating point; the edges decide
    assert S.s_bin(0.6999) == "[0.60, 0.70)"
    assert S.s_bin(0.7) == "[0.70, 0.77]"
    assert S.s_bin(0.77) == "[0.70, 0.77]"


def test_plain_params_and_jsonable():
    p = S.plain_params(
        {"every": np.int64(3), "band_rel": np.float64(0.1), "coin_share": 0.5, "btc_share": 0.25}
    )
    assert p == {"coin_share": 0.5, "btc_share": 0.25, "band_rel": 0.1, "every": 3}
    assert type(p["every"]) is int
    with pytest.raises(ValueError, match="integral"):
        S.plain_params({"every": 3.5, "band_rel": 0.1, "coin_share": 0.5, "btc_share": 0.25})
    got = S.jsonable(
        {
            "a": np.float64("nan"),
            "b": (np.int64(2), np.bool_(True)),
            "c": np.arange(2),
            "d": pd.Timestamp("2023-01-01", tz="UTC"),
            "e": math.inf,
        }
    )
    assert got == {"a": None, "b": [2, True], "c": [0, 1], "d": "2023-01-01T00:00:00+00:00", "e": None}


def test_gate_statuses_and_the_verdict_rules():
    assert S.gate_status(True, 1.2) == "PASS"
    assert S.gate_status(False, 0.3) == "FAIL"
    assert S.gate_status(False, float("nan")) == "MISSING"
    assert S.gate_status(True, None) == "MISSING"
    yes = dict.fromkeys(("E1", "E2", "E3", "E4", "E5"), True)
    assert S.train_verdict(yes) == {"verdict": "LOOK DUE", "look_due": True}
    assert S.train_verdict({**yes, "E2": False}) == {"verdict": "NO EDGE", "look_due": False}
    assert S.train_verdict({**yes, "E1": False, "E3": False}) == {"verdict": "NO EDGE", "look_due": False}
    for e in ("E3", "E4", "E5"):
        assert S.train_verdict({**yes, e: False}) == {"verdict": "INCONCLUSIVE", "look_due": False}
    assert S.final_verdict({**yes, "E6": True}) == "EDGE"
    assert S.final_verdict({**yes, "E6": False}) == "INCONCLUSIVE"
    assert S.final_verdict({**yes, "E6": None}) == "INCONCLUSIVE"
    assert S.final_verdict({**yes, "E6": True}, stopped=True) == "INCONCLUSIVE"
    assert S.final_verdict({**yes, "E1": False, "E6": True}) == "NO EDGE"
    passing = dict.fromkeys(S.GATES, "PASS")
    assert S.headline("EDGE", passing) == "CANDIDATE FOR AUDIT"
    assert S.headline("EDGE", {**passing, "G5": "PASS (weak)"}) == "CANDIDATE FOR AUDIT"
    assert S.headline("EDGE", {**passing, "G6": "MISSING", "G8": "FAIL"}) == (
        "EDGE, NOT A CANDIDATE (G6 MISSING, G8 FAIL)"
    )
    assert S.headline("NO EDGE", passing) == "NO EDGE"
    assert S.headline("INCONCLUSIVE", passing) == "INCONCLUSIVE"


def test_e6_by_hand():
    assert S.e6_parts(1.0, 2.0, 0.9, 0.99) == {
        "holds": True,
        "sharpe_positive": True,
        "half_train_sharpe": True,
        "beats_b4": True,
        "beats_b3_median": True,
    }
    assert (
        S.e6_parts(1.0, 2.0000001, 0.9, 0.99)["half_train_sharpe"] is False
    )  # >= 0.5 x, exactly half passes
    assert S.e6_parts(1.0, -3.0, 1.0, 0.5) == {
        "holds": False,
        "sharpe_positive": True,
        "half_train_sharpe": True,
        "beats_b4": False,
        "beats_b3_median": True,
    }  # equal to B4 fails
    assert not S.e6_parts(1.0, 1.0, 0.0, 1.0)["beats_b3_median"]  # equal to the median fails
    assert not S.e6_parts(0.0, -1.0, -1.0, -1.0)["holds"]  # a Sharpe of 0 is not > 0
    assert not S.e6_parts(float("nan"), 1.0, 0.0, 0.0)["holds"]


def test_stitched_metrics_add_the_fold_totals():
    r = pd.Series([0.1, -0.1, 0.05])
    got = S.stitched_metrics(
        r,
        [
            {"fills": 2, "turnover": 0.5, "cost": 0.001},
            {"fills": 1, "turnover": 0.25, "cost": 0.002, "cost_usd": 3.0},
        ],
    )
    assert got == {**S.series_metrics(r), "fills": 3, "turnover": 0.75, "cost": 0.003, "cost_usd": 3.0}
    assert S.series_metrics(r)["total_return"] == pytest.approx(1.1 * 0.9 * 1.05 - 1, rel=1e-15)
    assert S.series_metrics(r)["max_drawdown"] == pytest.approx(-0.1, rel=1e-15)
    assert S.series_metrics(r)["worst_day"] == -0.1


def test_fragility_compares_outcomes_and_the_sharpe_gap():
    gates = dict.fromkeys(S.GATES, "FAIL")
    a = {"E1": True, "E2": False, "E3": True, "gates": {**gates, "G5": "PASS"}, "sharpe": 1.0}
    assert S.fragility(a, {**a, "sharpe": 1.25}) == {"fragile": False, "differ": [], "sharpe_gap": 0.25}
    assert S.fragility(a, {**a, "sharpe": 1.2500001})["fragile"]
    assert S.fragility(a, {**a, "sharpe": float("nan")})["fragile"]
    weak = {**a, "gates": {**a["gates"], "G5": "PASS (weak)", "G6": "MISSING"}}
    assert not S.fragility(a, weak)["fragile"]  # PASS (weak) passes; MISSING fails like FAIL
    flip = S.fragility(a, {**a, "E2": True, "gates": {**a["gates"], "G7": "PASS"}})
    assert flip["fragile"] and flip["differ"] == ["E2", "G7"]


def test_git_state_counts_untracked_files_but_not_ignored_ones(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "a.txt").write_text("a\n")
    git("add", ".")
    git("commit", "-q", "-m", "c")
    state = S.git_state(repo)
    assert len(state["commit"]) == 40 and not state["dirty"]
    (repo / "ignored").mkdir()
    (repo / "ignored" / "x.txt").write_text("x\n")
    assert not S.git_state(repo)["dirty"]
    (repo / "new").mkdir()
    (repo / "new" / "b.txt").write_text("b\n")
    state = S.git_state(repo)
    assert state["dirty"] and state["changes"] == ["?? new/b.txt"]  # untracked files count, one by one
    shutil.rmtree(repo / "new")
    (repo / "a.txt").write_text("changed\n")
    assert S.git_state(repo)["dirty"]
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RuntimeError, match="git rev-parse HEAD failed"):
        S.git_state(plain)


def test_the_config_hash_covers_the_plan_s_files(tmp_path, monkeypatch):
    paths = S.frozen_paths()
    named = [
        f"research/rebalance-steady/{f}"
        for f in ("PLAN.md", "DATA.md", "study.py", "run_train.py", "freeze.py", "run_validate.py")
    ]
    named += [f"lab/runner/{f}" for f in ("portfolio.py", "reference.py", "interface.py", "steady.py")]
    named += [
        "lab/data/panel.py",
        "lab/data/catalog.py",
        "lab/data/external.py",
        "lab/config.py",
        "config/costs.yaml",
        "config/splits.yaml",
        "config/risk_levels.yaml",
        "pyproject.toml",
        "uv.lock",
    ]
    named += [
        p.relative_to(S.REPO).as_posix()
        for d in ("lab/search", "lab/validation")
        for p in (S.REPO / d).glob("*.py")
    ]
    assert paths == sorted(set(named))
    assert not any(p.endswith(("RESULTS.md", "RUNLOG.jsonl", "FROZEN.json")) for p in paths)
    cfg = copy_config(tmp_path / "config")
    hashes = S.file_hashes(cfg)
    assert hashes == S.file_hashes()  # the copy is byte-identical
    assert hashes["lab/runner/steady.py"] == S.sha256_file(S.REPO / "lab/runner/steady.py")
    (cfg / "costs.yaml").write_text((cfg / "costs.yaml").read_text() + "# changed\n")
    changed = S.file_hashes(cfg)
    assert [k for k in hashes if hashes[k] != changed[k]] == ["config/costs.yaml"]  # read from config_dir
    assert S.config_hash(changed) != S.config_hash(hashes)
    base = S.config_hash(hashes)
    monkeypatch.setitem(S.PINNED, "warmup", 121)
    assert S.config_hash(hashes) != base  # the pinned values are hashed too


def test_compare_hashes_and_the_risk_levels_exception(tmp_path, monkeypatch):
    """The recorded run read Steady's budget as TBD (as rebalance-steady's run 0 did), written into every copy
    here, so each case differs from the record in the one change it names (#55)."""

    def config(name: str) -> Path:
        cfg = copy_config(tmp_path / name)
        set_steady_budget(cfg, "TBD")
        return cfg

    cfg = config("config")
    rec = S.file_hashes(cfg)
    rec_hash = S.config_hash(rec)
    limits = sd.steady_limits(cfg)
    assert S.compare_hashes(rec, rec_hash, S.file_hashes(cfg), limits, cfg) == {
        "ok": True,
        "differs": [],
        "exception": None,
    }
    edit_risk(cfg, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    got = S.compare_hashes(rec, rec_hash, S.file_hashes(cfg), limits, cfg)
    assert got["ok"] and got["differs"] == [S.RISK_FILE]
    assert got["exception"]["risk_levels_sha256_recorded"] == rec[S.RISK_FILE]
    assert got["exception"]["risk_levels_sha256_now"] == S.sha256_file(cfg / "risk_levels.yaml")
    assert got["exception"]["limits_now"]["max_drawdown_budget"] == 0.3
    assert "never rescored" in got["exception"]["g6"]
    (cfg / "costs.yaml").write_text((cfg / "costs.yaml").read_text() + "# changed\n")
    got = S.compare_hashes(rec, rec_hash, S.file_hashes(cfg), limits, cfg)
    assert not got["ok"] and got["differs"] == ["config/costs.yaml", S.RISK_FILE]
    for i, (old, new, why) in enumerate(
        (
            ("min_cash_pct: 20", "min_cash_pct: 25", "changed its coins, min_cash or max_coin"),
            ("max_coin_pct: 60", "max_coin_pct: 55", "changed its coins, min_cash or max_coin"),
            ("coins: [BTC, ETH, USDC]", "coins: [ETH, BTC, USDC]", "changed its coins, min_cash or max_coin"),
            ("coins: [BTC, ETH, USDC]", "coins: [BTC, USDC]", "no longer reads"),
        )
    ):
        cfg2 = config(f"case{i}")
        edit_risk(cfg2, old, new)
        got = S.compare_hashes(rec, rec_hash, S.file_hashes(cfg2), limits, cfg2)
        assert not got["ok"] and got["differs"] == [S.RISK_FILE] and why in got["reason"]
    monkeypatch.setitem(S.PINNED, "warmup", 121)
    got = S.compare_hashes(rec, rec_hash, rec, limits, cfg)
    assert not got["ok"] and got["differs"] == ["<pinned values>"]
    cfg3 = config("c3")
    edit_risk(cfg3, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    got = S.compare_hashes(rec, rec_hash, S.file_hashes(cfg3), limits, cfg3)
    assert not got["ok"]  # risk_levels alone differs, but the pinned values changed too


def test_read_snapshot_stops_on_another_bars_hash(tmp_path):
    assert S.read_snapshot(tmp_path, synthetic=True) == {
        "snapshot_id": "synthetic",
        "bars_content_sha256": "synthetic",
    }
    with pytest.raises(S.Refusal, match="cannot read"):
        S.read_snapshot(tmp_path, synthetic=False)
    (tmp_path / "SNAPSHOT.json").write_text(
        json.dumps({"snapshot_id": "abc", "bars_content_sha256": "0" * 64})
    )
    with pytest.raises(S.Refusal, match="stop rule 2"):
        S.read_snapshot(tmp_path, synthetic=False)
    (tmp_path / "SNAPSHOT.json").write_text(
        json.dumps({"snapshot_id": "abc", "bars_content_sha256": S.BARS_SHA256})
    )
    assert S.read_snapshot(tmp_path, synthetic=False) == {
        "snapshot_id": "abc",
        "bars_content_sha256": S.BARS_SHA256,
    }


def test_the_synthetic_panels_have_the_plan_s_rows_and_dates(tmp_path):
    load = partial(
        S.load_study_panel, catalog_dir=tmp_path, config_dir=None, loader=S.synthetic_bar_loader(SEED)
    )
    k_train, b_train = load(S.SOURCE, S.TRAIN_LAST_CLOSE), load(S.ROBUSTNESS, S.TRAIN_LAST_CLOSE)
    k_val, b_val = load(S.SOURCE, S.VALIDATE_LAST_CLOSE), load(S.ROBUSTNESS, S.VALIDATE_LAST_CLOSE)
    assert (len(k_train), len(b_train), len(k_val), len(b_val)) == (2190, 1963, 2737, 2510)
    assert (
        k_train.index[0] == pd.Timestamp("2017-01-02", tz="UTC") and k_train.index[-1] == S.TRAIN_LAST_CLOSE
    )
    assert b_train.index[0] == pd.Timestamp("2017-08-18", tz="UTC")
    assert k_train.attrs["alignment"]["dropped"]["BTC"]["closes"] == ["2018-01-13T00:00:00+00:00"]
    assert k_val.index[-1] == S.VALIDATE_LAST_CLOSE
    assert sd.panel_hash(k_val.iloc[:2190]) == sd.panel_hash(
        k_train
    )  # a longer load starts with a shorter one
    assert sd.panel_hash(b_val.iloc[:1963]) == sd.panel_hash(b_train)
    w = sd.fold_window(k_val.index, np.arange(S.VALIDATE_TEST[0], S.VALIDATE_TEST[1] + 1))
    assert (w.first_h120, w.first_h1, w.t0) == tuple(
        pd.Timestamp(d, tz="UTC") for d in ("2022-09-04", "2023-01-01", "2023-01-02")
    )
    assert len(k_val.loc[w.t0 : w.last]) - 1 == S.VALIDATE_KEPT


def test_load_study_panel_never_asks_for_the_test_window(tmp_path):
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return S.synthetic_bar_loader(SEED)(*args, **kwargs)

    with pytest.raises(HoldoutWindowError):
        S.load_study_panel(
            S.SOURCE,
            S.VALIDATE_LAST_CLOSE + pd.Timedelta(days=1),
            catalog_dir=tmp_path,
            config_dir=None,
            loader=spy,
        )
    assert calls == []
    S.load_study_panel(S.SOURCE, S.TRAIN_LAST_CLOSE, catalog_dir=tmp_path, config_dir=None, loader=spy)
    assert [c["end"] for c in calls] == [S.TRAIN_LAST_CLOSE, S.TRAIN_LAST_CLOSE]


def test_load_study_panel_checks_what_load_panel_returns(tmp_path, monkeypatch):
    """Its own checks, not only load_panel's: a request after the cut never reaches load_panel, and a panel
    reaching past last_close (a broken loader) is refused."""
    calls = []

    def fake_load_panel(source, interval, *, last_close, **kwargs):
        calls.append(last_close)
        return K.loc[: last_close + pd.Timedelta(days=1)]  # one close too many

    K = S.load_study_panel(
        S.SOURCE,
        S.VALIDATE_LAST_CLOSE,
        catalog_dir=tmp_path,
        config_dir=None,
        loader=S.synthetic_bar_loader(SEED),
    )
    monkeypatch.setattr(S, "load_panel", fake_load_panel)
    with pytest.raises(HoldoutWindowError, match="the test window"):
        S.load_study_panel(
            S.SOURCE,
            S.VALIDATE_LAST_CLOSE + pd.Timedelta(hours=1),
            catalog_dir=tmp_path,
            config_dir=None,
            loader=None,
        )
    assert calls == []
    with pytest.raises(HoldoutWindowError, match="a close after"):
        S.load_study_panel(S.SOURCE, S.TRAIN_LAST_CLOSE, catalog_dir=tmp_path, config_dir=None, loader=None)
    assert calls == [S.TRAIN_LAST_CLOSE]


def test_real_runs_log_and_copy_into_the_study_folder_and_dry_runs_never_do(tmp_path):
    assert S.runlog_path(tmp_path, synthetic=False) == HERE / "RUNLOG.jsonl"
    assert S.tracked_dir(tmp_path, synthetic=False) == HERE
    assert S.runlog_path(tmp_path, synthetic=True) == tmp_path / "RUNLOG.jsonl"
    assert S.tracked_dir(tmp_path, synthetic=True) == tmp_path / "tracked"
    assert (
        S.DEFAULT_OUT == S.REPO / "results" / "rebalance-steady"
        and S.DEFAULT_CATALOG == S.REPO / "data" / "catalog"
    )


def test_real_folders_keep_real_runs_away_from_the_repo_s_runlog(tmp_path, monkeypatch):
    """#48: every folder a real run reads or writes is a stand-in in ``tmp_path``, the RUNLOG and the committed
    copies included, so the guard tests do not depend on the runs the repo has recorded (run 0 is in its RUNLOG)."""
    out, catalog_dir = real_folders(monkeypatch, tmp_path)
    for path in (out, catalog_dir, S.runlog_path(out, synthetic=False), S.tracked_dir(out, synthetic=False)):
        assert tmp_path in Path(path).parents
    assert S.runlog_entries(S.runlog_path(out, synthetic=False)) == []


# ------------------------------------------------------------------------------- run_train start guards


def test_a_dirty_tree_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(DIRTY))
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"
    assert RT.main(train_args(out, cfg)) == 2
    assert "dirty" in capsys.readouterr().err and not out.exists()
    real_folders(monkeypatch, tmp_path)  # real data too, in the pinned (here: stand-in) folders
    assert RT.main([]) == 2
    assert "dirty" in capsys.readouterr().err and not S.DEFAULT_OUT.exists()


def test_dry_run_switches_are_refused_on_real_data(tmp_path, capsys):
    for flag in ("--fast", "--allow-dirty"):
        assert RT.main(["--out-dir", str(tmp_path / "out"), flag]) == 2
        assert "synthetic dry runs only" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_run_0_runs_once(tmp_path, clean_git, capsys):
    out = tmp_path / "out"
    (out / "train").mkdir(parents=True)
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 2
    assert "run 0 runs once" in capsys.readouterr().err
    assert list((out / "train").iterdir()) == []


@pytest.mark.parametrize(
    "k, match", [("0", "run 0 is run without --amendment"), ("3", "INCONCLUSIVE"), ("-1", "numbered 1..2")]
)
def test_amendment_numbers_outside_1_and_2_are_refused(tmp_path, clean_git, capsys, k, match):
    out = tmp_path / "out"
    (out / "train" / "run0").mkdir(parents=True)
    (out / "train" / "run0" / "summary.json").write_text("{}")
    assert RT.main(train_args(out, copy_config(tmp_path / "config"), "--amendment", k)) == 2
    assert match in capsys.readouterr().err


def test_an_amendment_run_needs_the_previous_start_and_a_fresh_name(tmp_path, clean_git, capsys):
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"
    train = out / "train"
    (train / "run0").mkdir(parents=True)
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 2
    assert "run0/summary.json does not exist" in capsys.readouterr().err
    (train / "run0" / "summary.json").write_text("{}")  # written at start: a crashed run 0 counts
    assert RT.main(train_args(out, cfg, "--amendment", "2")) == 2
    assert "run1/summary.json does not exist" in capsys.readouterr().err
    (train / "run1").mkdir()
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 2
    assert "is never resumed" in capsys.readouterr().err
    (train / "run1").rmdir()
    (train / "rebalance-steady-s1_a1_wf02").mkdir()
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 2
    assert "studies of amendment run 1 exist" in capsys.readouterr().err
    assert sorted(p.name for p in train.iterdir()) == ["rebalance-steady-s1_a1_wf02", "run0"]


def test_a_real_amendment_run_needs_its_plan_row(tmp_path, clean_git, monkeypatch, capsys):
    out, _ = real_folders(monkeypatch, tmp_path)
    (out / "train" / "run0").mkdir(parents=True)
    write_start(out, 0, "real", fast=False)
    plan = tmp_path / "PLAN.md"
    plan.write_text(_plan("- **A4, ...** no amendment run row\n"))
    monkeypatch.setattr(S, "PLAN", plan)
    real = ["--amendment", "1"]
    before = here_hashes()
    assert RT.main(real) == 2
    assert "no '- **Amendment run 1' row" in capsys.readouterr().err
    plan.write_text(_plan("- **Amendment run 1 (2026-12-01).** Bug, found by, test.\n"))
    assert RT.main(real) == 2  # past the row check, it stops at the snapshot: no catalog here
    assert "SNAPSHOT.json" in capsys.readouterr().err
    assert not (out / "train" / "run1").exists() and here_hashes() == before  # no RUNLOG line in the repo


def test_the_box_must_keep_the_headroom_from_the_limits_as_read(tmp_path, clean_git, capsys):
    cfg = copy_config(tmp_path / "config")
    edit_risk(cfg, "max_coin_pct: 60", "max_coin_pct: 50")
    out = tmp_path / "out"
    assert RT.main(train_args(out, cfg)) == 2
    assert "refuse the search box" in capsys.readouterr().err and not out.exists()


# -------------------------------------------------------------------------------- run_train, run 0


def test_the_start_record_and_the_runlog_come_before_any_bar(tmp_path, clean_git, monkeypatch):
    cfg = copy_config(tmp_path / "config")
    set_steady_budget(cfg, "TBD")  # the start record of a TBD budget (G6 MISSING), set up here (#55)
    out = tmp_path / "out"
    seen = {}

    def spy_factory(seed):
        def loader(*args, **kwargs):
            seen["summary"] = json.loads((out / "train" / "run0" / "summary.json").read_text())
            seen["runlog"] = (out / "RUNLOG.jsonl").read_text().splitlines()
            raise S.Stop("enough")

        return loader

    monkeypatch.setattr(S, "synthetic_bar_loader", spy_factory)
    assert RT.main(train_args(out, cfg)) == 3
    start = seen["summary"]["start"]
    assert seen["summary"]["status"] == "started" and "panels" not in seen["summary"]
    assert start["config_hash"] == S.config_hash(start["file_hashes"]) and start[
        "file_hashes"
    ] == S.file_hashes(cfg)
    assert start["risk_limits"]["min_cash"] == 0.2 and start["risk_limits"]["max_coin"] == 0.6
    assert start["risk_limits"]["max_drawdown_budget_pct"] == "TBD"
    assert start["risk_limits"]["sha256"] == S.sha256_file(cfg / "risk_levels.yaml")
    assert start["g6_budget"] == {
        "source_run": 0,
        "max_drawdown_budget": None,
        "max_drawdown_budget_pct": "TBD",
        "sha256": start["risk_limits"]["sha256"],
    }
    assert start["git"] == CLEAN and start["data"] == "synthetic" and start["fast"]
    line = json.loads(seen["runlog"][0])
    assert len(seen["runlog"]) == 1 and line["run"] == 0 and line["config_hash"] == start["config_hash"]
    after = summary(out)
    assert after["status"] == "stopped: Stop: enough" and after["start"] == seen["summary"]["start"]


def test_the_test_window_guard_stops_the_run(tmp_path, clean_git, monkeypatch):
    """Stop rule 5: a loader that returns a bar after 2024-07-01 00:00 UTC stops the run."""
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"

    original = S.synthetic_bar_loader

    def leaky_factory(seed):
        inner = original(seed)

        def loader(*args, **kwargs):
            bars = inner(*args, **kwargs)
            extra = bars.iloc[[-1]].copy()
            extra.index = pd.DatetimeIndex([S.VALIDATE_LAST_CLOSE + pd.Timedelta(days=1)], name="ts").as_unit(
                "us"
            )
            leaked = pd.concat([bars, extra])
            leaked.attrs = bars.attrs
            return leaked

        return loader

    monkeypatch.setattr(S, "synthetic_bar_loader", leaky_factory)
    assert RT.main(train_args(out, cfg)) == 3
    assert summary(out)["status"].startswith("stopped: HoldoutWindowError")


def test_a_crash_is_recorded_and_raised(tmp_path, clean_git, monkeypatch):
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"

    def broken(seed):
        def loader(*args, **kwargs):
            raise KeyError("boom")

        return loader

    monkeypatch.setattr(S, "synthetic_bar_loader", broken)
    with pytest.raises(KeyError):
        RT.main(train_args(out, cfg))
    assert summary(out)["status"].startswith("crashed: KeyError")


def test_run_0_names_its_studies_and_counts_every_trial(train0):
    out = train0["out"]
    s = summary(out)
    n = s["start"]["settings"]["n_trials"]
    names = [
        f"rebalance-steady-s{seed}_{part}"
        for seed in (0, 1)
        for part in ("final", "wf00", "wf01", "wf02", "wf03")
    ]
    assert S.study_dirs(out / "train") == names
    assert s["status"] == "complete" and s["results"]["trials"]["n_raw"] == 10 * n
    assert s["results"]["trials"]["n_strict"] == 10 * n + 21
    trials = pd.read_parquet(out / "train" / "run0" / "trials.parquet")
    assert len(trials) == 10 * n and set(trials["run"]) == {0} and set(trials["seed"]) == {0, 1}
    ctx = json.loads(trials["context"].iloc[0])
    assert ctx["config_hash"] == s["start"]["config_hash"] and ctx["min_cash"] == 0.2 and ctx["run"] == 0
    assert (
        ctx["max_drawdown_budget_pct"] == "TBD"
        and ctx["risk_levels_sha256"] == s["start"]["risk_limits"]["sha256"]
    )
    np.testing.assert_allclose(trials["w_btc"], trials["params_coin_share"] * trials["params_btc_share"])
    csv = pd.read_csv(out / "tracked" / "trials.csv")
    assert len(csv) == len(trials) and list(csv.columns) == list(trials.columns)
    assert [json.loads(x)["run"] for x in (out / "RUNLOG.jsonl").read_text().splitlines()] == [0]


def test_run_0_reproduces_s_from_the_chosen_params(train0, tmp_path):
    """The stitched S in oos.parquet is the H120 harness on the chosen per-fold params (section 8)."""
    out, cfg = train0["out"], train0["cfg"]
    s = summary(out)
    K = S.load_study_panel(
        S.SOURCE,
        S.TRAIN_LAST_CLOSE,
        catalog_dir=tmp_path,
        config_dir=cfg,
        loader=S.synthetic_bar_loader(SEED),
    )
    assert sd.panel_hash(K) == s["panels"]["KRAKEN"]["hash"]
    fn = partial(sd.steady_backtest, limits=sd.steady_limits(cfg), costs=Costs.from_yaml(cfg / "costs.yaml"))
    folds = walk_forward(len(K), train_size=730, test_size=365, expanding=True)
    oos = pd.read_parquet(out / "train" / "run0" / "oos.parquet")
    for label in ("A", "B"):
        params = s["results"]["seeds"][label]["params"]
        pieces = []
        for p, f in zip(params, folds, strict=True):
            w = sd.fold_window(K.index, f.test)
            pieces.append(sd.kept_returns(sd.run_h120(fn, p, K, w), w.t0))
        r = pd.concat(pieces)
        assert len(r) == 1456
        np.testing.assert_array_equal(r.to_numpy(), oos[f"S_{label}"].to_numpy())
        assert (
            S.sharpe(r)
            == s["results"]["seeds"][label]["sharpe"]
            == s["results"]["seeds"][label]["e1"]["sharpe"]
        )


def test_run_0_s_verdict_gates_and_counts_follow_the_rules(train0):
    s = summary(train0["out"])
    r = s["results"]
    settings = s["start"]["settings"]
    a, b = r["seeds"]["A"], r["seeds"]["B"]
    assert r["E"]["E1"] == a["e1"]["holds"] == (a["e1"]["sharpe"] > a["e1"]["p95"])
    assert r["E"]["E2"] == a["e2"]["holds"] == (a["e2"]["d"] > 0 and a["e2"]["p"] < 0.05)
    assert r["E"]["E3"] == a["e3"]["holds"] == (a["e3"]["sharpe_S_2x"] > a["e3"]["sharpe_B4_2x"])
    assert r["E"]["E4"] == (not r["fragility"]["fragile"])
    assert r["E"]["E5"] == (r["binance"]["e1"]["holds"] and r["binance"]["e2"]["holds"])
    assert r["train_verdict"] == S.train_verdict(r["E"])
    for seed in (a, b):
        g = seed["gates"]
        assert g["G6"] == "MISSING" and g["G9"] == "NOT RUN"  # the budget is TBD
        assert g["G1"] == ("PASS" if seed["overfitting_report"]["oos_sharpe_annual"] >= 1.0 else "FAIL")
        assert g["G2"] == ("PASS" if seed["stitched"]["S_2x"]["sharpe"] > 0.5 else "FAIL")
        st = seed["stitched"]
        assert g["G7"] == (
            "PASS" if st["S"]["sharpe"] > max(st["B1"]["sharpe"], st["B2"]["sharpe"]) else "FAIL"
        )
        assert g["G8"] == ("PASS" if seed["regimes"]["split"]["pass"] else "FAIL")
        assert g["G5"] == seed["plateau"]["verdict"] and len(seed["plateau"]["steps"]) == 8
        assert seed["dsr"]["n_raw"] == 10 * settings["n_trials"]
        assert seed["stitched"]["B3"]["draws"] == settings["b3_draws"]
        assert seed["trades_per_parameter"]["value"] == seed["trades_per_parameter"]["kept_fills"] / 4
        assert len(seed["folds"]) == 4 and seed["theta_final"]["label"] == "IN-SAMPLE"
        assert (
            st["S"]["fills"]
            == sum(f["k"] for f in seed["folds"])
            == seed["trades_per_parameter"]["kept_fills"]
        )
        assert st["B4"]["fills"] == 0 and st["B4"]["cost"] == 0.0  # B4 pays nothing in the kept rows
        assert st["S"]["cost"] == pytest.approx(sum(f["metrics"]["cost"] for f in seed["folds"]), rel=1e-12)
    assert r["fragility"] == S.fragility(
        {**a["E"], "gates": a["gates"], "sharpe": a["sharpe"]},
        {**b["E"], "gates": b["gates"], "sharpe": b["sharpe"]},
    )
    assert r["headline_if_edge"] == S.headline("EDGE", a["gates"])
    assert r["triage_required"] is False and r["failed_trials"] == []
    ev = pd.read_parquet(train0["out"] / "train" / "run0" / "evaluations.parquet")
    counts = ev.groupby(["kind", "source"]).size().to_dict()
    assert (
        counts[("B3", "KRAKEN")] == 2 * settings["b3_draws"]
        and counts[("B3", "BINANCE")] == settings["b3_draws"]
    )
    assert counts[("plateau", "KRAKEN")] == 16 and counts[("theta_final_in_sample", "KRAKEN")] == 2
    for kind in ("S", "S_2x", "B1", "B2", "B4", "B4_2x", "B5"):  # one row per fold piece and seed
        assert (ev.loc[(ev["kind"] == kind) & (ev["source"] == "KRAKEN"), "fold"] != "stitched").sum() == 8
    assert (ev.loc[(ev["kind"] == "S") & (ev["source"] == "BINANCE"), "fold"] != "stitched").sum() == 4
    assert counts[("phase", "KRAKEN")] == sum(r["trials"]["phase_runs"].values())
    assert sum(r["trials"]["phase_runs"].values()) == sum(p["every"] for x in (a, b) for p in x["params"])
    assert len(pd.read_csv(train0["out"] / "tracked" / "evaluations.csv")) == len(ev)


def _fail_fold_0_trials(original, params, bars, **kwargs):
    if len(bars) == 730 and params["coin_share"] > 0.5:  # only fold 0's training slice has 730 rows
        raise ValueError("an injected failure")
    return original(params, bars, **kwargs)


def test_failed_trials_are_reported_with_their_error_for_triage(tmp_path, clean_git, monkeypatch, capsys):
    """Stop rule 4: the phase finishes, and every failed trial is listed with the error Optuna logged."""
    monkeypatch.setattr(sd, "steady_backtest", partial(_fail_fold_0_trials, sd.steady_backtest))
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 0
    r = summary(out)["results"]
    assert r["triage_required"] and r["failed_trials"]
    for f in r["failed_trials"]:
        assert f["study"].endswith("_wf00") and f["state"] == "FAIL" and f["params_coin_share"] > 0.5
        assert f["fail_reason"].startswith(f"Trial {f['number']} failed with parameters: {{'coin_share': ")
        assert f["fail_reason"].endswith("because of the following error: ValueError('an injected failure').")
    assert len(r["failure_log"]) == len(r["failed_trials"])
    assert "ValueError: an injected failure" in r["failure_log"][0]["traceback"]
    trials = pd.read_csv(out / "tracked" / "trials.csv")
    failed = trials[trials["state"] == "FAIL"]
    assert len(failed) == len(r["failed_trials"]) and failed["fail_reason"].str.contains("injected").all()
    assert r["trials"]["n_raw"] == len(trials)
    # stop rule 4: no freeze (so no look) before the triage
    set_look_due(out, True)
    cfg = tmp_path / "config"
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "triage them first" in capsys.readouterr().err and not (out / "FROZEN.json").exists()
    note = "no code bug: the failure was injected by the test"
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg), "--triaged", note]) == 0
    assert json.loads((out / "FROZEN.json").read_text())["triage_note"] == note


def _b4_that_trades(params_rebalance, panel, window, params, costs, book, *, like=None):
    """A broken B4: one rebalance inside the block, at zero cost (so 1x and 2x still agree)."""
    w_btc, w_eth = sd.targets(params)
    piece = sd.h1_slice(panel, window, like=like)
    return params_rebalance(
        {"w_btc": w_btc, "w_eth": w_eth, "n_rebalances": 1, "seed": 0}, piece, Costs.zero()
    )


def _kept_fills_off_by_one(original, result, t0):
    return original(result, t0) + 1


@pytest.mark.parametrize(
    "target, replacement, message",
    [
        (
            "static_b4",
            lambda: partial(_b4_that_trades, sd.random_rebalance),
            "B4 traded inside the kept rows",
        ),
        (
            "kept_fills",
            lambda: partial(_kept_fills_off_by_one, sd.kept_fills),
            "differ from walk_forward_optimize",
        ),
    ],
)
def test_the_consistency_stops_fire(tmp_path, clean_git, monkeypatch, target, replacement, message):
    """The run's own consistency checks (section 8) stop it when the harness disagrees with itself."""
    monkeypatch.setattr(sd, target, replacement())
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    status = summary(out)["status"]
    assert status.startswith("stopped: Stop:") and message in status


def test_dry_runs_never_write_into_the_repo(train0):
    assert here_hashes() == train0["before"]
    assert (train0["out"] / "RUNLOG.jsonl").is_file() and (train0["out"] / "tracked" / "trials.csv").is_file()


def _fails_on_high_coin_share(fn, params, bars):
    if params["coin_share"] > 0.5:
        raise ValueError("a failing trial")
    return fn(params, bars)


def test_an_amendment_run_counts_every_run_and_keeps_run_0_s_budget(fresh, clean_git, tmp_path):
    out, cfg = fresh
    # a crashed study of run 0 with a failed trial: every trial in every state counts (section 12)
    K = S.load_study_panel(
        S.SOURCE,
        S.TRAIN_LAST_CLOSE,
        catalog_dir=tmp_path,
        config_dir=cfg,
        loader=S.synthetic_bar_loader(SEED),
    )
    fn = partial(sd.steady_backtest, limits=sd.steady_limits(cfg), costs=Costs.from_yaml(cfg / "costs.yaml"))
    extra = run_study(
        "rebalance-steady-s0_wf09",
        partial(_fails_on_high_coin_share, fn),
        list(sd.SPECS),
        K.iloc[:400],
        out / "train",
        SearchConfig(n_trials=6, n_workers=1, seed=3),
    )
    assert set(extra["state"]) == {"COMPLETE", "FAIL"}
    edit_risk(cfg, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")  # read at run 1's start
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 0
    s = summary(out, 1)
    n = s["start"]["settings"]["n_trials"]
    trials = pd.read_csv(out / "tracked" / "trials.csv")
    assert len(trials) == 20 * n + 6 and (trials["state"] == "FAIL").sum() == (extra["state"] == "FAIL").sum()
    assert s["results"]["failed_trials"] == [] and not s["results"]["triage_required"]  # run 1's own trials
    assert s["start"]["risk_limits"]["max_drawdown_budget"] == 0.3  # its own reading, recorded
    assert s["start"]["g6_budget"]["max_drawdown_budget"] is None  # G6 keeps run 0's
    assert s["results"]["seeds"]["A"]["gates"]["G6"] == "MISSING"
    studies = S.study_dirs(out / "train")
    assert len(studies) == 21 and sum("_a1_" in x for x in studies) == 10
    assert s["results"]["trials"]["n_raw"] == 20 * n + 6 and s["results"]["trials"]["this_run"] == 10 * n
    assert s["results"]["seeds"]["A"]["dsr"]["n_raw"] == 20 * n + 6
    assert "rebalance-steady-s0_wf09" in s["results"]["pbo_per_study"]
    assert s["results"]["earlier_runs"]["0"]["verdict"] == summary(out, 0)["results"]["train_verdict"]
    assert set(pd.read_csv(out / "tracked" / "trials.csv")["run"]) == {0, 1}
    assert set(pd.read_csv(out / "tracked" / "evaluations.csv")["run"]) == {0, 1}
    # G3 and G4 come from a report over EVERY study of every run (section 12), crashed ones included
    for label in ("A", "B"):
        a = s["results"]["seeds"][label]
        oos = pd.read_parquet(out / "train" / "run1" / "oos.parquet")[f"S_{label}"]
        combined = {
            "oos_returns": oos,
            "wf_efficiency": a["wf_efficiency"],
            "studies": studies,
            "total_trials": 20 * n + 6,
        }
        assert a["overfitting_report"] == S.jsonable(overfitting_report(combined, out / "train"))
    assert [json.loads(x)["run"] for x in (out / "RUNLOG.jsonl").read_text().splitlines()] == [0, 1]
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 2  # once


# --------------------------------------------------------------------------------------------- freeze


def test_freeze_refuses_when_the_look_is_not_due(fresh, clean_git, capsys):
    out, cfg = fresh
    set_look_due(out, False)
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "no validate look" in capsys.readouterr().err and not (out / "FROZEN.json").exists()
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg), "--any-verdict"]) == 0  # synthetic only


def test_freeze_writes_frozen_json_and_a_byte_identical_copy(frozen):
    out, cfg = frozen
    f = json.loads((out / "FROZEN.json").read_text())
    s = summary(out)
    assert (out / "tracked" / "FROZEN.json").read_bytes() == (out / "FROZEN.json").read_bytes()
    assert (
        f["run"] == 0
        and f["config_hash"] == s["start"]["config_hash"]
        and f["file_hashes"] == S.file_hashes(cfg)
    )
    assert f["train_outputs_sha256"] == S.tree_hashes(out / "train") and f["deviations"] == []
    assert f["theta_final"] == s["results"]["theta_final"]
    assert f["fold_params"] == {lab: s["results"]["seeds"][lab]["params"] for lab in ("A", "B")}
    assert (
        f["panels"]["KRAKEN"]["hash"] == s["panels"]["KRAKEN"]["hash"]
        and f["panels"]["BINANCE"]["rows"] == 1963
    )
    assert (
        f["risk_limits_train_start"] == s["start"]["risk_limits"]
        and f["g6_budget"] == s["start"]["g6_budget"]
    )
    assert f["snapshot"] == s["start"]["snapshot"] and f["seeds"] == {"A": 0, "B": 1}
    assert f["n_trials_per_study"] == s["start"]["settings"]["n_trials"]
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2  # once


def test_freeze_refuses_a_changed_hash(fresh, clean_git, capsys):
    out, cfg = fresh
    set_look_due(out, True)
    (cfg / "costs.yaml").write_text((cfg / "costs.yaml").read_text() + "# a change\n")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "config/costs.yaml" in capsys.readouterr().err and not (out / "FROZEN.json").exists()


def test_freeze_takes_the_risk_levels_exception_and_never_rescores_g6(fresh, clean_git):
    out, cfg = fresh
    set_look_due(out, True)
    edit_risk(cfg, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    f = json.loads((out / "FROZEN.json").read_text())
    dev = f["deviations"][0]
    assert dev["risk_levels_sha256_now"] == S.sha256_file(cfg / "risk_levels.yaml")
    assert dev["risk_levels_sha256_recorded"] == summary(out)["start"]["file_hashes"][S.RISK_FILE]
    assert f["train_start"]["file_hashes"][S.RISK_FILE] != f["file_hashes"][S.RISK_FILE]  # both recorded
    assert f["g6_budget"]["max_drawdown_budget"] is None and f["gates"]["A"]["G6"] == "MISSING"


def test_freeze_refuses_a_risk_levels_change_that_moves_the_limits(fresh, clean_git, capsys):
    out, cfg = fresh
    set_look_due(out, True)
    edit_risk(cfg, "min_cash_pct: 20", "min_cash_pct: 21")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "min_cash" in capsys.readouterr().err and not (out / "FROZEN.json").exists()


def test_freeze_reports_the_last_run_only_when_it_is_complete(fresh, clean_git, tmp_path, capsys):
    """INTERPRETATIONS["reported_run"]: a crashed or stopped last run is rerun as an amendment run, so freeze.py
    never falls back to the run it superseded (the old reading froze run 0 here, its trial count short of the
    trials under train/)."""
    out, cfg = fresh
    set_look_due(out, True)
    assert FZ.reported_run(out / "train")[0] == 0
    (out / "train" / "run1").mkdir()
    (out / "train" / "run1" / "summary.json").write_text(json.dumps({"status": "crashed: X"}))
    with pytest.raises(S.Refusal, match="run 1, the last train run, is not complete"):
        FZ.reported_run(out / "train")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "'crashed: X'" in capsys.readouterr().err and not (out / "FROZEN.json").exists()
    (out / "train" / "run1" / "summary.json").write_text(json.dumps({"status": "stopped: Stop: x"}))
    with pytest.raises(S.Refusal, match="not complete"):
        FZ.reported_run(out / "train")
    with pytest.raises(S.Refusal, match="no train run"):
        FZ.reported_run(tmp_path / "nothing")
    real = tmp_path / "real" / "train" / "run0"
    real.mkdir(parents=True)
    (real / "summary.json").write_text(
        json.dumps({"status": "complete", "start": {"data": "real"}, "results": {}})
    )
    assert FZ.main(["--out-dir", str(tmp_path / "real"), "--any-verdict"]) == 2  # dry runs only
    assert "synthetic dry runs only" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------- the look


def test_the_look_runs_once_with_its_consistency_checks(frozen):
    out, cfg = frozen
    assert RV.main(validate_args(out, cfg)) == 0
    look = json.loads((out / "validate" / "look.json").read_text())
    assert (out / "validate" / "STARTED").is_file()
    assert look["consistency"] == {
        "panel_hashes": {"BINANCE": True, "KRAKEN": True},
        "theta_final_reproduced": {"A": True, "B": True},
    }
    assert look["kept_rows"] == 546 and look["window_closes"] == {
        "first_h120": "2022-09-04T00:00:00+00:00",
        "first_h1": "2023-01-01T00:00:00+00:00",
        "t0": "2023-01-02T00:00:00+00:00",
        "last": "2024-07-01T00:00:00+00:00",
    }
    e6 = look["E6"]
    assert e6["holds"] == (
        e6["sharpe"] > 0
        and e6["sharpe"] >= 0.5 * e6["train_sharpe_A"]
        and e6["sharpe"] > e6["sharpe_b4"]
        and e6["sharpe"] > e6["b3_sharpe_p50"]
    )
    frozen_json = json.loads((out / "FROZEN.json").read_text())
    assert e6["train_sharpe_A"] == frozen_json["train_sharpe"]["A"]
    assert look["E"] == {**frozen_json["E"], "E6": e6["holds"]}
    assert look["verdict"] == S.final_verdict(look["E"])
    assert look["headline"] == S.headline(look["verdict"], frozen_json["gates"]["A"])
    runlog = [json.loads(x) for x in (out / "RUNLOG.jsonl").read_text().splitlines()]
    assert [x["run"] for x in runlog] == [0, "validate"]
    csv = pd.read_csv(out / "tracked" / "validate.csv")
    assert {"S_A", "B3_A", "B4_A", "S_B", "S_A_binance", "S_2x_A", "S_2x_B", "B1", "B2", "B5_A"} <= set(
        csv["id"]
    )
    assert csv.loc[csv["id"] == "S_A", "sharpe"].item() == pytest.approx(e6["sharpe"], rel=1e-15, abs=0)
    assert RV.main(validate_args(out, cfg)) == 2  # no second look
    (out / "validate" / "STARTED").unlink()
    assert RV.main(validate_args(out, cfg)) == 2  # look.json alone also refuses
    # a copy of the results without validate/, or validate/ deleted in place: the RUNLOG still holds the look
    copy = out.parent / "copy"
    shutil.copytree(out, copy)
    shutil.rmtree(copy / "validate")
    assert RV.main(validate_args(copy, cfg)) == 2 and not (copy / "validate").exists()
    shutil.rmtree(out / "validate")
    assert RV.main(validate_args(out, cfg)) == 2 and not (out / "validate").exists()


def test_started_is_written_before_any_validate_bar(frozen, monkeypatch):
    out, cfg = frozen
    seen = {}

    def spy_factory(seed):
        def loader(*args, **kwargs):
            seen["started"] = (out / "validate" / "STARTED").is_file()
            seen["runlog"] = (out / "RUNLOG.jsonl").read_text().splitlines()
            raise KeyError("crash inside the look")

        return loader

    monkeypatch.setattr(S, "synthetic_bar_loader", spy_factory)
    with pytest.raises(KeyError):
        RV.main(validate_args(out, cfg))
    assert seen["started"] and json.loads(seen["runlog"][-1])["run"] == "validate"
    assert RV.main(validate_args(out, cfg)) == 2  # a crashed look counts as the look


def test_a_failed_consistency_check_spends_the_look(frozen, capsys):
    out, cfg = frozen
    assert RV.main(validate_args(out, cfg, seed=SEED + 1)) == 3  # other bars: the train rows no longer hash
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["verdict"] == "INCONCLUSIVE" and look["stopped"].startswith("Stop: the train rows")
    assert (out / "validate" / "STARTED").is_file()
    assert RV.main(validate_args(out, cfg)) == 2


def test_theta_final_must_reproduce_its_logged_returns_at_the_look(fresh, clean_git):
    out, cfg = fresh
    set_look_due(out, True)
    theta = summary(out)["results"]["theta_final"]["A"]
    path = out / "train" / theta["study"] / "returns" / f"trial_{theta['trial_number']:06d}.parquet"
    logged = pd.read_parquet(path)
    logged.iloc[5, 0] += 1e-12
    logged.to_parquet(path)  # changed before the freeze, so FROZEN.json records it
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    assert RV.main(validate_args(out, cfg)) == 3
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["verdict"] == "INCONCLUSIVE" and "does not reproduce" in look["stopped"]
    assert "'A': False, 'B': True" in look["stopped"]


def test_the_look_refuses_a_dirty_tree_or_changed_files(frozen, monkeypatch, capsys):
    out, cfg = frozen
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(DIRTY))
    assert RV.main(validate_args(out, cfg)) == 2
    assert "dirty" in capsys.readouterr().err
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
    cfg2 = copy_config(out.parent / "config2", cfg)
    (cfg2 / "splits.yaml").write_text((cfg2 / "splits.yaml").read_text() + "# a change\n")
    assert RV.main(validate_args(out, cfg2)) == 2
    assert "config/splits.yaml" in capsys.readouterr().err
    trial = next((out / "train").glob("*/returns/trial_000000.parquet"))
    original = trial.read_bytes()
    trial.write_bytes(original + b"\0")
    assert RV.main(validate_args(out, cfg)) == 2
    assert "changed since the freeze" in capsys.readouterr().err
    trial.write_bytes(original)
    copy = out / "tracked" / "FROZEN.json"
    copy.write_text(copy.read_text() + " ")
    assert RV.main(validate_args(out, cfg)) == 2
    assert "byte-identical" in capsys.readouterr().err
    assert not (out / "validate").exists()


def test_the_look_s_other_refusals(fresh, clean_git, capsys, monkeypatch):
    out, cfg = fresh
    assert RV.main(validate_args(out, cfg)) == 2
    assert "run freeze.py first" in capsys.readouterr().err
    set_look_due(out, False)
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg), "--any-verdict"]) == 0
    assert RV.main(validate_args(out, cfg)) == 2
    assert "no validate look" in capsys.readouterr().err
    monkeypatch.setattr(S, "DEFAULT_OUT", out)  # a real look in the pinned (here: stand-in) folders
    monkeypatch.setattr(S, "DEFAULT_CATALOG", out.parent / "no-catalog")
    monkeypatch.setattr(S, "HERE", out.parent / "here")  # and a stand-in RUNLOG, not the repo's (#48)
    real = []
    assert RV.main(real) == 2  # FROZEN.json is synthetic
    assert "synthetic train run" in capsys.readouterr().err
    assert RV.main([*real, "--allow-dirty"]) == 2
    assert "synthetic dry runs only" in capsys.readouterr().err
    assert not (out / "validate").exists()


def test_the_look_follows_the_risk_levels_exception(fresh, clean_git):
    out, cfg = fresh
    set_look_due(out, True)
    edit_risk(cfg, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    assert RV.main(validate_args(out, cfg)) == 0
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["gates_train_A"]["G6"] == "MISSING"  # never rescored


# ------------------------------------------------------------- the folders a run may use (#46: code bugs)


def fake_repo(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """``S.REPO`` and ``S.DEFAULT_OUT`` moved into ``tmp_path``: a guard that failed would write there, never into
    the real study folder."""
    repo = tmp_path / "repo"
    default = repo / "results" / "rebalance-steady"
    monkeypatch.setattr(S, "REPO", repo)
    monkeypatch.setattr(S, "DEFAULT_OUT", default)
    return repo, default


def test_check_out_dir_and_check_real_paths_by_hand(tmp_path):
    for inside in (
        S.DEFAULT_OUT,
        S.DEFAULT_OUT / "x",
        S.REPO,
        S.REPO / "scratch",
        S.REPO / "results" / "other",
    ):
        with pytest.raises(S.Refusal, match="never writes into"):
            S.check_out_dir(inside, synthetic=True)
    S.check_out_dir(tmp_path / "scratch", synthetic=True)
    S.check_out_dir(S.DEFAULT_OUT, synthetic=False)  # a real run's folder is check_real_paths' job
    with pytest.MonkeyPatch.context() as mp:  # the study folder itself, wherever it is
        mp.setattr(S, "DEFAULT_OUT", tmp_path / "study")
        with pytest.raises(S.Refusal, match="never writes into"):
            S.check_out_dir(tmp_path / "study", synthetic=True)
    S.check_real_paths(S.DEFAULT_OUT, None, S.DEFAULT_CATALOG)
    S.check_real_paths(S.DEFAULT_OUT, S.REPO / "config", None)
    with pytest.raises(S.Refusal, match="--out-dir"):
        S.check_real_paths(tmp_path / "out", None, S.DEFAULT_CATALOG)
    with pytest.raises(S.Refusal, match="--config-dir"):
        S.check_real_paths(S.DEFAULT_OUT, copy_config(tmp_path / "config"), S.DEFAULT_CATALOG)
    with pytest.raises(S.Refusal, match="--catalog-dir"):
        S.check_real_paths(S.DEFAULT_OUT, None, tmp_path / "catalog")
    with pytest.raises(S.Refusal, match="--out-dir"):
        S.check_paths(tmp_path / "out", None, None, synthetic=False)
    with pytest.raises(S.Refusal, match="never writes into"):
        S.check_paths(S.DEFAULT_OUT, None, None, synthetic=True)


def test_a_dry_run_never_writes_into_the_study_folder(train0, tmp_path, clean_git, monkeypatch, capsys):
    """Section 12: synthetic dry runs never in results/rebalance-steady/. A dry run there would block run 0, use up
    an amendment number, add synthetic trials to every later DSR and PBO, and could leave a FROZEN.json that blocks
    the real freeze."""
    repo, default = fake_repo(monkeypatch, tmp_path)
    cfg = copy_config(tmp_path / "config")
    for out in (default, repo / "scratch"):
        assert RT.main(train_args(out, cfg)) == 2
        assert "never writes into" in capsys.readouterr().err and not out.exists()
    shutil.copytree(train0["out"], default)  # a dry run that got there before the guard existed
    before = S.tree_hashes(default)
    assert RT.main(train_args(default, cfg, "--amendment", "1")) == 2
    assert "never writes into" in capsys.readouterr().err and S.tree_hashes(default) == before  # no run1/
    set_look_due(default, True)
    before = S.tree_hashes(default)
    assert FZ.main(["--out-dir", str(default), "--config-dir", str(cfg)]) == 2
    assert "never writes into" in capsys.readouterr().err
    assert RV.main(validate_args(default, cfg)) == 2
    assert "never writes into" in capsys.readouterr().err
    # nothing written: no run1/, FROZEN.json, validate/ or RUNLOG line
    assert S.tree_hashes(default) == before


def test_an_amendment_run_continues_the_same_kind_of_run(tmp_path, clean_git, monkeypatch, capsys):
    cfg = copy_config(tmp_path / "config")
    cases = [  # (earlier runs as (data, fast), this run's args, message)
        ([("real", False)], train_args(tmp_path / "o1", cfg, "--amendment", "1"), "run 0 was a real run"),
        ([("synthetic", False)], train_args(tmp_path / "o2", cfg, "--amendment", "1"), "(fast False)"),
        (
            [("synthetic", True), ("real", False)],
            train_args(tmp_path / "o3", cfg, "--amendment", "2"),
            "run 1 was a real run",
        ),
    ]
    for runs, args, message in cases:
        out = Path(args[args.index("--out-dir") + 1])
        for j, (data, fast) in enumerate(runs):
            write_start(out, j, data, fast)
        assert RT.main(args) == 2
        assert message in capsys.readouterr().err and not (out / "train" / f"run{len(runs)}").exists()
    out = tmp_path / "o4"
    (out / "train" / "run0").mkdir(parents=True)
    (out / "train" / "run0" / "summary.json").write_text("{}")
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 2
    assert "cannot read run 0's start record" in capsys.readouterr().err
    # a real amendment over a synthetic run 0 in the (stand-in) study folder
    real_out, _ = real_folders(monkeypatch, tmp_path / "real")
    write_start(real_out, 0, "synthetic", True, status="complete")
    plan = tmp_path / "PLAN.md"
    plan.write_text(_plan("- **Amendment run 1 (2026-12-01).** Bug, found by, test.\n"))
    monkeypatch.setattr(S, "PLAN", plan)
    assert RT.main(["--amendment", "1"]) == 2
    assert (
        "run 0 was a synthetic run" in capsys.readouterr().err and not (real_out / "train" / "run1").exists()
    )


def test_real_runs_use_the_pinned_folders_only(tmp_path, clean_git, monkeypatch, capsys):
    """Sections 4 and 12 pin config/costs.yaml, splits.yaml and risk_levels.yaml; section 11 pins the look's marker
    at results/rebalance-steady/validate/STARTED. A real run with another config folder (zero pool fee here) or
    another results or catalog folder is refused by all three scripts before anything is written."""
    out, catalog_dir = real_folders(monkeypatch, tmp_path)
    cheap = copy_config(tmp_path / "cheap")
    path = cheap / "costs.yaml"
    path.write_text(path.read_text().replace("pool_fee_bps: 5", "pool_fee_bps: 0", 1))
    elsewhere = tmp_path / "elsewhere"
    for main in (RT.main, RV.main):
        for args, flag in (
            (["--config-dir", str(cheap)], "--config-dir"),
            (["--out-dir", str(elsewhere)], "--out-dir"),
            (["--catalog-dir", str(tmp_path / "other-catalog")], "--catalog-dir"),
        ):
            assert main(args) == 2
            assert flag in capsys.readouterr().err
    assert not out.exists() and not elsewhere.exists()
    # config/ itself is accepted: past the path guard, run_train stops at the missing SNAPSHOT.json
    assert RT.main(["--config-dir", str(S.REPO / "config")]) == 2
    assert "SNAPSHOT.json" in capsys.readouterr().err and not out.exists()
    # freeze.py on a real run: the same folders
    for folder in (out, elsewhere):
        write_start(folder, 0, "real", False, status="complete")
    assert FZ.main(["--config-dir", str(cheap)]) == 2
    assert "--config-dir" in capsys.readouterr().err
    assert FZ.main(["--out-dir", str(elsewhere)]) == 2
    assert "--out-dir" in capsys.readouterr().err
    assert not (out / "FROZEN.json").exists() and not (elsewhere / "FROZEN.json").exists()


def test_the_runlog_keeps_a_deleted_run_or_look_from_running_again(tmp_path, clean_git, monkeypatch, capsys):
    """INTERPRETATIONS["runlog_guard"]: the tracked RUNLOG (here a stand-in) is consulted, so deleting results/
    reopens neither a train run nor the look (stop rules 6, 7 and 9)."""
    out, _ = real_folders(monkeypatch, tmp_path)
    here = tmp_path / "here"
    monkeypatch.setattr(S, "HERE", here)
    S.append_runlog(
        here / "RUNLOG.jsonl", {"utc": "t", "script": "run_train.py", "run": 0, "data": "synthetic"}
    )
    S.append_runlog(here / "RUNLOG.jsonl", {"utc": "t", "script": "run_validate.py", "data": "synthetic"})
    assert RT.main([]) == 2  # synthetic lines do not count for real runs: it gets to the snapshot
    assert "SNAPSHOT.json" in capsys.readouterr().err
    assert RV.main([]) == 2
    assert "run freeze.py first" in capsys.readouterr().err
    S.append_runlog(here / "RUNLOG.jsonl", {"utc": "t0", "script": "run_train.py", "run": 0, "data": "real"})
    assert RT.main([]) == 2
    assert "already records real run 0 (started t0)" in capsys.readouterr().err
    S.append_runlog(here / "RUNLOG.jsonl", {"utc": "t1", "script": "run_validate.py", "data": "real"})
    assert RV.main([]) == 2
    assert "records a real look started t1" in capsys.readouterr().err
    assert not out.exists()
    assert S.runlog_entries(tmp_path / "none.jsonl") == []


# ------------------------------------------------------------ the numbers, recomputed (#47: test gaps)


def study_panels(cfg: Path, tmp_path: Path, last=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    load = partial(
        S.load_study_panel, catalog_dir=tmp_path, config_dir=cfg, loader=S.synthetic_bar_loader(SEED)
    )
    last = S.TRAIN_LAST_CLOSE if last is None else last
    return load(S.SOURCE, last), load(S.ROBUSTNESS, last)


def adapters(cfg: Path):
    limits = sd.steady_limits(cfg)
    c1 = Costs.from_yaml(cfg / "costs.yaml")
    c2 = c1.stressed()
    return (
        limits,
        c1,
        partial(sd.steady_backtest, limits=limits, costs=c1),
        partial(sd.steady_backtest, limits=limits, costs=c2),
    )


def harness(panel, windows, params, fn1, c1, n_draws, like=None):
    """S, B3 and B4 per fold, by hand from steady.py, as PLAN.md section 8 says: S's kept fills k_i and S's book
    V, B3 seeds 10 j + i at 1x from V, B4 at 1x from V."""
    s, b4, b3, ks, books = [], [], [], [], []
    for i, (w, p) in enumerate(zip(windows, params, strict=True)):
        res = sd.run_h120(fn1, p, panel, w, like=like)
        k, book = sd.kept_fills(res, w.t0), sd.book_value(res, w, c1)
        s.append(sd.kept_returns(res, w.t0))
        b3.append(sd.random_b3(panel, w, p, k, c1, book, i, n_draws=n_draws, like=like)["returns"])
        b4.append(sd.kept_returns(sd.static_b4(panel, w, p, c1, book, like=like), w.t0))
        ks.append(k)
        books.append(book)
    return pd.concat(s), np.hstack(b3), pd.concat(b4), ks, books


E1_KEYS = ("sharpe", "p5", "p50", "p95", "rank_p", "holds")
E2_KEYS = ("d", "p", "holds", "n_resamples", "mean_block", "seed")


def test_run_0_numbers_are_recomputed_from_their_inputs(train0_budget, tmp_path):
    """Every reported number of the train phase rebuilt from its inputs with steady.py (a wrong seed, book, cost
    model, comparator, price series or gate input in run_train.py fails here)."""
    out, cfg = train0_budget["out"], train0_budget["cfg"]
    s = summary(out)
    r, settings = s["results"], s["start"]["settings"]
    limits, c1, fn1, fn2 = adapters(cfg)
    K, Bn = study_panels(cfg, tmp_path)
    folds = walk_forward(len(K), train_size=730, test_size=365, expanding=True)
    windows = [sd.fold_window(K.index, f.test) for f in folds]
    train = out / "train"
    studies = S.study_dirs(train)
    n_raw = r["trials"]["n_raw"]
    assert s["start"]["g6_budget"]["max_drawdown_budget"] == 1.0
    for label in ("A", "B"):
        a = r["seeds"][label]
        params = a["params"]
        s_ret, b3, b4, ks, books = harness(K, windows, params, fn1, c1, settings["b3_draws"])
        assert [f["k"] for f in a["folds"]] == ks and [f["book_usd"] for f in a["folds"]] == books
        e1 = sd.e1_rank(s_ret, b3)
        assert {k: a["e1"][k] for k in E1_KEYS} == {k: e1[k] for k in E1_KEYS}
        assert a["stitched"]["B3"]["total_return"] == S.jsonable(
            mc.percentiles(np.prod(1.0 + b3, axis=1) - 1.0)
        )
        e2 = sd.paired_bootstrap(s_ret, b4, settings["bootstrap_resamples"], sd.MEAN_BLOCK, seed=0)
        assert {k: a["e2"][k] for k in E2_KEYS} == {k: e2[k] for k in E2_KEYS}
        s2 = pd.concat(
            [sd.kept_returns(sd.run_h120(fn2, p, K, w), w.t0) for w, p in zip(windows, params, strict=True)]
        )
        b1 = pd.concat([sd.kept_returns(sd.buy_and_hold_b1(K, w, c1), w.t0) for w in windows])
        b2 = pd.concat([sd.kept_returns(sd.fifty_fifty_b2(K, w, c1), w.t0) for w in windows])
        sh = {"S": S.sharpe(s_ret), "S2": S.sharpe(s2), "B1": S.sharpe(b1), "B2": S.sharpe(b2)}
        st = a["stitched"]
        assert (st["S"]["sharpe"], st["S_2x"]["sharpe"], st["B1"]["sharpe"], st["B2"]["sharpe"]) == (
            sh["S"],
            sh["S2"],
            sh["B1"],
            sh["B2"],
        )
        assert a["e3"]["sharpe_S_2x"] == sh["S2"] and a["e3"]["sharpe_B4_2x"] == S.sharpe(b4)
        # B4's buy at the open of t0 is not a kept row
        assert st["B4"]["cost_usd"] == 0.0 and st["B4"]["cost"] == 0.0
        split = sd.regime_split(s_ret, sd.regime_table(K[("BTC", "close")], s_ret.index), benchmark=b4)
        assert a["regimes"]["split"] == S.jsonable(split)
        for step, logged in zip(sd.plateau_steps(params, limits), a["plateau"]["steps"], strict=True):
            r_step = pd.concat(
                [
                    sd.kept_returns(sd.run_h120(fn1, step["params"][i], K, w), w.t0)
                    for i, w in enumerate(windows)
                ]
            )
            assert logged["sharpe"] == S.sharpe(r_step)
        rep = overfitting_report(
            {
                "oos_returns": s_ret,
                "wf_efficiency": a["wf_efficiency"],
                "studies": studies,
                "total_trials": n_raw,
            },
            train,
        )
        assert a["overfitting_report"] == S.jsonable(rep)
        strict = stats.deflated_sharpe_ratio(
            s_ret.to_numpy(), sd.report_trial_sharpes(studies, train), n_trials=n_raw + 21
        )["dsr"]
        assert a["dsr"]["strict"] == strict and a["dsr"]["n_strict"] == n_raw + 21
        for f, p, fold in zip(a["phase_sensitivity"]["folds"], params, folds, strict=True):
            sharpes = [
                S.sharpe(sd.kept_returns(sd.run_h120(fn1, p, K, w), w.t0))
                for w in (sd.fold_window(K.index, fold.test, warmup=sd.WARMUP + j) for j in range(p["every"]))
            ]
            assert (f["min"], f["median"], f["max"]) == (
                float(np.min(sharpes)),
                float(np.median(sharpes)),
                float(np.max(sharpes)),
            )
        unpaid = []
        for i in range(3):
            last = sd.run_h120(fn1, params[i], K, windows[i]).loc[windows[i].last]
            nxt = sd.targets(params[i + 1])
            unpaid.append(abs(nxt[0] - last["w_BTC"]) + abs(nxt[1] - last["w_ETH"]))
        assert a["unpaid_turnover"]["boundaries"] == unpaid
        # the gates: their input numbers, and the table from those numbers
        assert a["gate_inputs"] == S.jsonable(S.gate_inputs(sh, rep, 1.0))
        assert a["gates"] == S.gate_table(sh, rep, a["plateau"]["verdict"], split["pass"], 1.0)
        assert a["gates"]["G6"] == ("PASS" if rep["mc_drawdown_worst5pct"] >= -1.0 else "FAIL") == "PASS"
    # E5 on Binance: seed A's params, Binance's own k_i and book, the same B3 seeds and bootstrap
    a = r["seeds"]["A"]
    s_bn, b3_bn, b4_bn, ks_bn, books_bn = harness(
        Bn, windows, a["params"], fn1, c1, settings["b3_draws"], like=K
    )
    bn = r["binance"]
    assert [f["k"] for f in bn["folds"]] == ks_bn and [f["book_usd"] for f in bn["folds"]] == books_bn
    assert ks_bn != [f["k"] for f in a["folds"]] or books_bn != [f["book_usd"] for f in a["folds"]]
    e1 = sd.e1_rank(s_bn, b3_bn)
    e2 = sd.paired_bootstrap(s_bn, b4_bn, settings["bootstrap_resamples"], sd.MEAN_BLOCK, seed=0)
    assert {k: bn["e1"][k] for k in E1_KEYS} == {k: e1[k] for k in E1_KEYS}
    assert {k: bn["e2"][k] for k in E2_KEYS} == {k: e2[k] for k in E2_KEYS}
    assert r["E"]["E5"] == (e1["holds"] and e2["holds"])


def _rep(**changes) -> dict:
    """An overfitting_report's gate numbers; the raw-count DSR (0.90) fails where the effective one (0.96) passes."""
    base = {
        "oos_sharpe_annual": 1.2,
        "dsr_effective_count": 0.96,
        "dsr_raw_count": 0.90,
        "pbo_mean": 0.25,
        "mc_drawdown_worst5pct": -0.72,
    }
    return {**base, **changes}


def test_the_gate_table_by_hand():
    """Numbers that separate every wiring choice: G2 on S at 2x (not 1x), G7 against B1 AND B2, G3 at the
    effective count (not the raw one), G6 as drawdown >= -budget (a fraction)."""
    sh = {"S": 1.2, "S2": 0.4, "B1": 1.0, "B2": 1.5}
    nan = float("nan")
    assert S.gate_table(sh, _rep(), "PASS (weak)", True, None) == {
        "G1": "PASS",
        "G2": "FAIL",  # S at 1x (1.2) would pass
        "G3": "PASS",  # the raw-count DSR (0.90) would fail
        "G4": "PASS",  # 0.25 passes
        "G5": "PASS (weak)",
        "G6": "MISSING",  # the budget is TBD
        "G7": "FAIL",  # above B1, below B2: 'or' would pass
        "G8": "PASS",
        "G9": "NOT RUN",
    }

    def gate(name, sharpes=sh, rep=None, budget=None, g5="FAIL", regimes=False):
        return S.gate_table(sharpes, _rep() if rep is None else rep, g5, regimes, budget)[name]

    assert gate("G4", rep=_rep(pbo_mean=0.26)) == "FAIL"
    assert (
        gate("G1", rep=_rep(oos_sharpe_annual=1.0)) == "PASS"
        and gate("G1", rep=_rep(oos_sharpe_annual=0.99)) == "FAIL"
    )
    assert gate("G3", rep=_rep(dsr_effective_count=0.95)) == "PASS"
    assert gate("G3", rep=_rep(dsr_effective_count=0.94, dsr_raw_count=0.99)) == "FAIL"
    assert (
        gate("G2", sharpes={**sh, "S2": 0.5}) == "FAIL" and gate("G2", sharpes={**sh, "S2": 0.51}) == "PASS"
    )
    assert gate("G7", sharpes={**sh, "S": 1.6}) == "PASS"
    assert gate("G7", sharpes={**sh, "S": 1.5}) == "FAIL"  # equal to B2 is not above it
    assert gate("G7", sharpes={**sh, "S": 1.6, "B1": 1.7}) == "FAIL"
    assert gate("G6", budget=0.70) == "FAIL" and gate("G6", budget=0.75) == "PASS"  # p5 -0.72
    assert gate("G6", budget=0.72) == "PASS"  # exactly at the budget passes
    assert gate("G6", rep=_rep(mc_drawdown_worst5pct=0.0), budget=0.30) == "PASS"
    assert gate("G5", g5="PASS") == "PASS" and gate("G8") == "FAIL" and gate("G8", regimes=True) == "PASS"
    # a NaN number makes its gate MISSING (it fails), whatever the others say
    assert gate("G1", rep=_rep(oos_sharpe_annual=nan)) == "MISSING"
    assert gate("G2", sharpes={**sh, "S2": nan}) == "MISSING"
    assert gate("G3", rep=_rep(dsr_effective_count=nan)) == "MISSING"
    assert gate("G4", rep=_rep(pbo_mean=nan)) == "MISSING"
    assert gate("G6", rep=_rep(mc_drawdown_worst5pct=nan), budget=0.75) == "MISSING"
    for key in ("S", "B1", "B2"):
        assert gate("G7", sharpes={**sh, "S": 1.6, key: np.float64(nan)}) == "MISSING"
    assert S.gate_status(True) == "MISSING" and S.gate_status(True, 1.0, None) == "MISSING"
    assert S.gate_inputs(sh, _rep(), 0.3) == {
        "G1": 1.2,
        "G2": 0.4,
        "G3": 0.96,
        "G4": 0.25,
        "G6": {"mc_drawdown_worst5pct": -0.72, "budget": 0.3},
        "G7": {"S": 1.2, "B1": 1.0, "B2": 1.5},
    }


def _drop_close(instrument: str, close: str):
    def wrap(original):
        def factory(seed):
            loader = original(seed)

            def wrapped(name, interval, start=None, end=None, catalog_dir=None):
                bars = loader(name, interval, start=start, end=end, catalog_dir=catalog_dir)
                return bars.drop(pd.Timestamp(close, tz="UTC")) if name == instrument else bars

            return wrapped

        return factory

    return wrap


def _another_snapshot(original):
    return lambda catalog_dir, synthetic: {"snapshot_id": "another", "bars_content_sha256": "synthetic"}


def _b4_2x_differs(original):
    def static_b4(panel, window, params, costs, book, *, like=None):
        if costs.pool_fee_bps > Costs.from_yaml().pool_fee_bps:  # the 2x model
            params = {**params, "coin_share": params["coin_share"] * 0.99}
        return original(panel, window, params, costs, book, like=like)

    return static_b4


def _b3_fills_off(original, binance_only: bool = True):
    def random_b3(*args, like=None, **kwargs):
        out = original(*args, like=like, **kwargs)
        return {**out, "fills": out["fills"] + 1} if like is not None or not binance_only else out

    return random_b3


@pytest.mark.parametrize(
    "module, target, wrap, message",
    [
        (
            "S",
            "synthetic_bar_loader",
            _drop_close("BTC/USD.KRAKEN", "2019-06-01"),
            "train rows, the plan counts",
        ),
        ("S", "read_snapshot", _another_snapshot, "is not the one SNAPSHOT.json names"),
        ("sd", "static_b4", _b4_2x_differs, "B4 at 2x differs from B4 at 1x"),
        ("sd", "random_b3", _b3_fills_off, "BINANCE fold 0: a B3 draw's kept fills differ"),
    ],
)
def test_more_stops_fire(tmp_path, clean_git, monkeypatch, module, target, wrap, message):
    """The plan's stops: the train row counts (section 3), the snapshot SNAPSHOT.json names, B4 at 2x equal to B4
    at 1x (section 8), and B3's kept fills equal to k_i on Binance too (E5's "same count")."""
    mod = {"S": S, "sd": sd}[module]
    monkeypatch.setattr(mod, target, wrap(getattr(mod, target)))
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    status = summary(out)["status"]
    assert status.startswith("stopped:") and message in status, status


def test_a_binance_close_missing_inside_a_fold_stops_the_run(tmp_path, clean_git, monkeypatch):
    """Binance from 2017-08-17 (one close earlier) without 2019-06-01 (inside fold 1): still 1963 rows, so only
    the slice assert of section 8 can stop it."""
    original = S.synthetic_bar_loader

    def factory(seed):
        loader = original(seed)

        def wrapped(instrument, interval, start=None, end=None, catalog_dir=None):
            bars = loader(instrument, interval, start=start, end=end, catalog_dir=catalog_dir)
            if instrument.endswith(".BINANCE"):
                kraken = loader(instrument.replace("USDT.BINANCE", "/USD.KRAKEN"), interval)
                extra = kraken.loc[[pd.Timestamp("2017-08-17", tz="UTC")]]
                extra.attrs = {}
                attrs = bars.attrs
                bars = pd.concat([extra, bars.drop(pd.Timestamp("2019-06-01", tz="UTC"))])
                bars.attrs = attrs
            return bars

        return wrapped

    monkeypatch.setattr(S, "synthetic_bar_loader", factory)
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    s = summary(out)
    assert s["panels"]["BINANCE"]["rows"] == 1963
    assert s["status"].startswith("stopped: SliceMismatchError"), s["status"]


def test_theta_final_and_neighbourhood_rechecks_stop(train0, tmp_path):
    out, cfg = train0["out"], train0["cfg"]
    s = summary(out)
    train = out / "train"
    theta = s["results"]["theta_final"]["A"]
    trials = S.trial_table(train, [theta["study"]])
    done = trials[trials["state"] == "COMPLETE"]
    other = int(done.loc[done["number"] != theta["trial_number"], "number"].iloc[0])
    K, _ = study_panels(cfg, tmp_path)
    limits, _, fn1, _ = adapters(cfg)
    ctx = {"fn1": fn1, "K": K, "train": train, "limits": limits}
    ev = RT.Evaluations(0)
    assert (
        RT.theta_final_in_sample(ctx, theta, theta["study"], S.FAST, ev, "A")["trial_number"]
        == theta["trial_number"]
    )
    with pytest.raises(S.Stop, match="does not reproduce"):
        RT.theta_final_in_sample(ctx, {**theta, "trial_number": other}, theta["study"], S.FAST, ev, "A")
    RT.neighbourhood(trials, theta["params"])
    with pytest.raises(S.Stop, match="stable region recomputed"):
        RT.neighbourhood(trials, {**theta["params"], "every": theta["params"]["every"] + 1})


def test_a_changed_start_record_stops_the_run_and_is_recorded(tmp_path, clean_git, monkeypatch):
    def tampering(args, summary, run_dir, ctx, settings):
        summary["start"]["utc"] = "changed"
        return {}

    monkeypatch.setattr(RT, "train_phase", tampering)
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    assert summary(out)["status"] == "stopped: Stop: the start fields changed during the run"


def test_the_plan_s_sizes_are_pinned_and_used_without_fast(tmp_path, clean_git, monkeypatch):
    """N = 200 is amendment A1 and feeds the DSR; B3 1000 and the bootstrap 10,000 are section 10's."""
    assert S.PLAN_SETTINGS == S.Settings(
        n_trials=200,
        b3_draws=1000,
        bootstrap_resamples=10_000,
        mc_sims=1000,
        shuffle_sims=5000,
        degrade_sims=1000,
        profile_mc_sims=1000,
    )
    assert S.PINNED["settings"] == {
        "n_trials": 200,
        "b3_draws": 1000,
        "bootstrap_resamples": 10_000,
        "mc_sims": 1000,
        "shuffle_sims": 5000,
        "degrade_sims": 1000,
        "profile_mc_sims": 1000,
    }

    def stop(args, summary, run_dir, ctx, settings):
        raise S.Stop(f"settings seen: {settings.n_trials}")

    monkeypatch.setattr(RT, "train_phase", stop)
    out = tmp_path / "out"
    args = [a for a in train_args(out, copy_config(tmp_path / "config")) if a != "--fast"]
    assert RT.main(args) == 3
    s = summary(out)
    assert s["start"]["settings"] == S.PINNED["settings"] and s["start"]["fast"] is False
    assert s["status"].endswith("settings seen: 200")


def test_overshoot_by_hand():
    limits = {"min_cash": 0.2, "max_coin": 0.6}
    got = S.overshoot([0.61, 0.5, 0.3, 0.2], [0.1, 0.31, 0.3, 0.2], limits)
    # one close with a coin above max_coin, one with cash below min_cash
    assert got == {"lowest_cash": 1.0 - 0.5 - 0.31, "highest_coin": 0.61, "closes_in_breach": 2}
    assert S.overshoot([0.2], [0.61], limits)["closes_in_breach"] == 1  # ETH alone
    assert S.overshoot([0.6 + 5e-10], [0.0], limits)["closes_in_breach"] == 0  # LIMIT_TOL
    assert S.overshoot([0.5], [0.3 + 5e-10], limits)["closes_in_breach"] == 0


# ------------------------------------------------------------------ freeze and the look (#47: test gaps)


def test_freeze_takes_the_amendment_run_and_its_start_record(fresh, clean_git):
    """The reported run is the last one (amendment run 1 here), and its own start record is the one compared: run
    1 read another risk_levels.yaml (a budget), so run 0's record would have given a deviation."""
    out, cfg = fresh
    edit_risk(cfg, "max_drawdown_budget_pct: TBD", "max_drawdown_budget_pct: 30")
    assert RT.main(train_args(out, cfg, "--amendment", "1")) == 0
    p1 = out / "train" / "run1" / "summary.json"
    data = json.loads(p1.read_text())
    data["results"]["train_verdict"] = {"verdict": "LOOK DUE", "look_due": True}
    p1.write_text(json.dumps(data))
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    f = json.loads((out / "FROZEN.json").read_text())
    assert f["run"] == 1 and f["train_start"]["config_hash"] == data["start"]["config_hash"]
    assert f["train_start"]["config_hash"] != summary(out, 0)["start"]["config_hash"]
    assert f["deviations"] == [] and f["trials"]["n_raw"] == data["results"]["trials"]["n_raw"]
    assert f["theta_final"] == data["results"]["theta_final"] and f["summary_sha256"] == S.sha256_file(p1)


def _with_frozen(out: Path, cfg: Path, edit) -> None:
    """Edit run 0's summary (``edit(results)``), mark the look due, and freeze."""
    path = out / "train" / "run0" / "summary.json"
    data = json.loads(path.read_text())
    data["results"]["train_verdict"] = {"verdict": "LOOK DUE", "look_due": True}
    edit(data["results"])
    path.write_text(json.dumps(data))
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0


def test_the_look_s_numbers_are_recomputed_from_their_inputs(train0_budget, tmp_path, clean_git):
    out = tmp_path / "out"
    shutil.copytree(train0_budget["out"], out)
    cfg = copy_config(tmp_path / "config", train0_budget["cfg"])
    # theta_final(A) := the final study's trial that trades most, so S also trades inside the warmup (k must
    # count the kept fills only)
    trials = pd.read_parquet(out / "train" / "run0" / "trials.parquet")
    final = trials[(trials["study"] == "rebalance-steady-s0_final") & (trials["state"] == "COMPLETE")]
    busy = final.sort_values("n_trades").iloc[-1]

    def edit(results):
        results["theta_final"]["A"].update(
            trial_number=int(busy["number"]),
            params=S.plain_params({n: busy[f"params_{n}"] for n in sd.PARAM_NAMES}),
        )

    _with_frozen(out, cfg, edit)
    assert RV.main(validate_args(out, cfg)) == 0
    look = json.loads((out / "validate" / "look.json").read_text())
    frozen = json.loads((out / "FROZEN.json").read_text())
    K, Bn = study_panels(cfg, tmp_path, S.VALIDATE_LAST_CLOSE)
    limits, c1, fn1, _ = adapters(cfg)
    w = sd.fold_window(K.index, np.arange(2190, 2737))
    theta = frozen["theta_final"]["A"]["params"]
    s_ret, b3, b4, ks, books = harness(K, [w], [theta], fn1, c1, frozen["settings"]["b3_draws"])
    rank = sd.e1_rank(s_ret, b3)
    res = sd.run_h120(fn1, theta, K, w)
    assert int((res["turnover"] > 0).sum()) - 1 != ks[0]  # S trades outside the kept rows too
    e6 = look["E6"]
    assert (e6["sharpe"], e6["sharpe_b4"], e6["b3_sharpe_p50"], e6["k"], e6["book_usd"]) == (
        S.sharpe(s_ret),
        S.sharpe(b4),
        rank["p50"],
        ks[0],
        books[0],
    )
    assert e6 == {**e6, **S.e6_parts(S.sharpe(s_ret), frozen["train_sharpe"]["A"], S.sharpe(b4), rank["p50"])}
    csv = pd.read_csv(out / "tracked" / "validate.csv").set_index("id")
    assert csv.loc["B3_A", "b3_sharpe_p95"] == pytest.approx(rank["p95"], rel=1e-15, abs=0)
    s_bn, b3_bn, b4_bn, ks_bn, _ = harness(Bn, [w], [theta], fn1, c1, frozen["settings"]["b3_draws"], like=K)
    d = look["descriptions"]["binance_A"]
    assert (d["sharpe"], d["sharpe_b4"], d["k"]) == (S.sharpe(s_bn), S.sharpe(b4_bn), ks_bn[0])
    assert d["b3"]["p50"] == sd.e1_rank(s_bn, b3_bn)["p50"]


def test_the_look_refuses_another_snapshot(frozen, monkeypatch, capsys):
    out, cfg = frozen
    monkeypatch.setattr(S, "read_snapshot", _another_snapshot(S.read_snapshot))
    assert RV.main(validate_args(out, cfg)) == 2
    assert "is not the frozen one" in capsys.readouterr().err and not (out / "validate").exists()


def test_a_validate_panel_with_a_missing_close_stops_the_look(frozen, monkeypatch):
    out, cfg = frozen
    monkeypatch.setattr(
        S, "synthetic_bar_loader", _drop_close("ETH/USD.KRAKEN", "2023-06-01")(S.synthetic_bar_loader)
    )
    assert RV.main(validate_args(out, cfg)) == 3
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["verdict"] == "INCONCLUSIVE" and "2736 rows, the plan counts 2737" in look["stopped"]


def test_a_b3_draw_with_other_fills_stops_the_look(frozen, monkeypatch):
    out, cfg = frozen
    monkeypatch.setattr(sd, "random_b3", _b3_fills_off(sd.random_b3, binance_only=False))
    assert RV.main(validate_args(out, cfg)) == 3
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["verdict"] == "INCONCLUSIVE" and "A KRAKEN: a B3 draw's kept fills differ" in look["stopped"]


def test_the_look_checks_frozen_json_against_the_summary(frozen, capsys):
    """FROZEN.json certifies nothing by itself: edited the same way in both copies (another logged trial as
    theta_final, another summary hash), the look refuses before STARTED."""
    out, cfg = frozen
    original = (out / "FROZEN.json").read_bytes()
    data = json.loads(original)
    for key, value in (
        ("theta_final", {**data["theta_final"], "A": {**data["theta_final"]["A"], "trial_number": 0}}),
        ("summary_sha256", "0" * 64),
        ("train_sharpe", {**data["train_sharpe"], "A": 9.0}),
    ):
        edited = json.dumps({**data, key: value}).encode()
        for path in (out / "FROZEN.json", out / "tracked" / "FROZEN.json"):
            path.write_bytes(edited)
        assert RV.main(validate_args(out, cfg)) == 2
        err = capsys.readouterr().err
        assert ("is not the summary" if key == "summary_sha256" else f"['{key}']") in err, err
    assert not (out / "validate").exists()


def test_an_edge_at_the_look_is_headlined_with_seed_a_s_train_gates(fresh, clean_git, monkeypatch):
    """The EDGE path of the look's verdict and headline (the synthetic data never reach it on their own)."""
    out, cfg = fresh
    gates = {}

    def edit(results):
        results["E"] = dict.fromkeys(("E1", "E2", "E3", "E4", "E5"), True)
        gates["A"] = {**results["seeds"]["A"]["gates"], "G1": "PASS", "G2": "FAIL"}
        gates["B"] = {**results["seeds"]["B"]["gates"], "G1": "FAIL", "G2": "PASS"}
        for label in ("A", "B"):
            results["seeds"][label]["gates"] = gates[label]

    _with_frozen(out, cfg, edit)
    real = S.e6_parts
    monkeypatch.setattr(S, "e6_parts", lambda *a: {**real(*a), "holds": True})
    assert RV.main(validate_args(out, cfg)) == 0
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["verdict"] == "EDGE" and look["E"]["E6"] is True
    assert look["headline"] == S.headline("EDGE", gates["A"]) and "G2 FAIL" in look["headline"]
    assert "G1 FAIL" not in look["headline"]
