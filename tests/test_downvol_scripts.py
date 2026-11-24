"""The downvol-steady study scripts (``research/downvol-steady/``: study.py, run_train.py, freeze.py, run_validate.py,
controls.py, throughput.py) against PLAN.md (vol-steady's plan, VP, with the downside measure, E1 on the q-only shifts of
amendment M1 and the strict count plus 2,400) sections 3-17: the start guards (dirty tree, pinned folders, amendment
rules, stop rule 18's trigger, the branch guard of stop rule 11, the feasibility check of stop rule 12 over every s x q,
the projection guard of stop rule 17, A1 and A0 before a real run), the start record and RUNLOG before any bar, the data
stops (stop rules 2 and 5), the consistency stops (stop rules 12-14 and the run's own rechecks), the config hash with
the full import closure, the freeze and the single look, A0 (its three control sets) and A1, and every reported number
recomputed from its inputs with lab.runner.downvol, lab.runner.volsteady and lab.runner.trend (the #47 standard): E1
from the q-only shifts and E1-whole from VP's whole-schedule shifts. vol-steady's script tests adapted. SYNTHETIC data
only: every run is a dry run in ``tmp_path`` and the real catalog loader is replaced by one that fails the test if it
is ever reached.

No test depends on what the committed PLAN.md holds today (TESTING.md #59, #68): every test that reads a plan reads a
stand-in built here (``stand_in_plan``), and the scripts' ``S.PLAN`` is pointed at one for every test. The one exception
is ``test_the_committed_plan_reads_as_a_real_run_will_read_it``, which checks only what the pre-registration fixes for
good (the branch line and section 15's heading) and accepts both states of A1/A0 (placeholders or records).
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from test_portfolio import edit_steady_entry, set_steady_budget

from lab.config import CONFIG_DIR
from lab.data import catalog
from lab.data.external import HoldoutWindowError
from lab.runner import downvol as D
from lab.runner import steady as sd
from lab.runner import trend as T
from lab.runner import volsteady as V
from lab.runner.portfolio import make_panel
from lab.runner.reference import Costs
from lab.search.report import overfitting_report
from lab.search.stability import stable_region
from lab.validation import montecarlo as mc
from lab.validation import stats

HERE = Path(__file__).resolve().parents[1] / "research" / "downvol-steady"


def _load(name: str, file: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


RT = _load("downvol_steady_run_train", "run_train.py")
FZ = _load("downvol_steady_freeze", "freeze.py")
RV = _load("downvol_steady_run_validate", "run_validate.py")
A0 = _load("downvol_steady_controls", "controls.py")
A1 = _load("downvol_steady_throughput", "throughput.py")
S = RT.S
# The plan file the guards read (A1/A0, the branch line, the amendment rows), as the module sets it: captured at
# import, before the autouse ``stand_in_plan_file`` fixture replaces it in every test (#73).
REAL_PLAN = S.PLAN
CLEAN = {"commit": "0" * 40, "dirty": False, "changes": []}
DIRTY = {"commit": "0" * 40, "dirty": True, "changes": ["?? stray.txt"]}
SEED = 7
QUICK = {"study": 0.1, "run": 0.001, "bootstrap": 0.1}


def _refuse_real_bars(*args, **kwargs):
    raise AssertionError("a test reached the real catalog loader")


@pytest.fixture(autouse=True)
def no_real_bars(monkeypatch):
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)


# A stand-in for PLAN.md: its header's branch line as the pre-registration words it, a '## 14-16.' heading before
# section 15 (as the real plan has), section 15 with amendment M1 and the A1 and A0 placeholder lines, and section 17.
BRANCH_LINE = (
    "- Branch: R. Steady drawdown budget **35%** (`max_drawdown_budget_pct: 35`), as read from "
    "`config/risk_levels.yaml`\n  (SHA-256 `d3f58253dfc2dbbe0ca5e54a4fa12489ab0e08827ecbc309e8ab2b7cc028723e`), "
    "owner-approved in writing on\n  2026-11-21.\n"
)
PLACEHOLDERS = (
    "- **A1:** the throughput timing (before run 0).\n- **A0:** the procedure controls (before run 0).\n"
)


def stand_in_plan(rows: str = PLACEHOLDERS) -> str:
    """A stand-in PLAN.md (never the committed one, #68) with ``rows`` as section 15's lines after M1."""
    return (
        "# downvol-steady: pre-registration (a stand-in written by the tests)\n\n"
        f"{BRANCH_LINE}\n"
        "## 14-16. Trial counting, protocol and outputs (VP 14-16, with one change)\n\n"
        "- **The strict trial count** is VP's (N_raw + 49) **plus 2,400**.\n\n"
        "## 15. Amendments\n\n"
        "- **M1 (2026-11-24, before any code): the reason corrected, and E1 judged with the share held fixed.**\n"
        "  - **E1 shifts only the volatility steps.** share_u(c_k) = s_fold(c_k) x q(c_(k+u)).\n"
        f"{rows}\n"
        "## 17. Code to build, and its tests (VP 17, adapted)\n\n- **`lab/runner/downvol.py`**\n"
    )


@pytest.fixture(autouse=True)
def stand_in_plan_file(monkeypatch, tmp_path_factory):
    """Every test's ``S.PLAN`` is a stand-in (placeholders in section 15), never the committed PLAN.md (#68)."""
    plan = tmp_path_factory.mktemp("plan") / "PLAN.md"
    plan.write_text(stand_in_plan())
    monkeypatch.setattr(S, "PLAN", plan)
    return plan


@pytest.fixture
def clean_git(monkeypatch):
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))


def quick_timing(seconds=QUICK):
    def fake(limits, costs, settings, n_trials):
        return {"seconds": dict(seconds), "timing_trials": 0, "timing_reps": 0, "n_trials": n_trials}

    return fake


@pytest.fixture
def fast_timing(monkeypatch):
    """The projection guard's re-timing, stubbed (TESTING.md #51: a coverage run is several times slower)."""
    monkeypatch.setattr(S, "measure_timing", quick_timing())


def copy_config(dst: Path, src: Path = CONFIG_DIR) -> Path:
    dst.mkdir(parents=True)
    for name in ("costs.yaml", "splits.yaml", "risk_levels.yaml"):
        shutil.copy(src / name, dst / name)
    return dst


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
        "--any-verdict",
        *extra,
    ]


def here_hashes() -> dict[str, str]:
    return {k: v for k, v in S.tree_hashes(HERE).items() if "__pycache__" not in k}


def summary(out: Path, k: int = 0) -> dict:
    return json.loads((out / "train" / f"run{k}" / "summary.json").read_text())


def set_verdict(out: Path, verdict: str, earned: bool, k: int = 0) -> None:
    """Stand in for run k's own verdict (the synthetic one is whatever the data give): its verdict, its own record
    (the headline as V.headline gives it on the run's points) and its reported record, which stop rule 18 rebuilds
    from the new own record and the earlier runs its start record says it is reported beside (#58)."""
    path = out / "train" / f"run{k}" / "summary.json"
    data = json.loads(path.read_text())
    r = data["results"]
    r["verdict"] = {"verdict": verdict, "label": verdict, "look_earned": earned}
    points = {(p["item"], p["point"]): p["value"] for p in r["points"]}
    r["own"].update(
        verdict=verdict, headline=V.headline(r["verdict"], points)["headline"], look_earned=earned
    )
    r["reported"].update(S.combine_reported(data["start"]["beside"], r["own"]))
    path.write_text(json.dumps(data))


def set_look_earned(out: Path, earned: bool, k: int = 0) -> None:
    set_verdict(out, "EDGE" if earned else "NO EDGE", earned, k)


# Amendments A1 and A0 as a real run needs them (INTERPRETATIONS["prior_amendments"]), written into PLAN.md section
# 15's placeholder lines; the real PLAN.md gets them only after A1 and A0 have run, so real-data tests that must get
# past this guard use a stand-in plan (TESTING.md #58, #59).
PRIOR_ROWS = (
    f"- **A1:** (2026-12-01) throughput on the built adapter: N = {S.PLAN_SETTINGS.n_trials} trials.\n"
    "- **A0:** (2026-12-01) procedure controls: stop rule 15: no alarm; power: no alarm.\n"
)


def section_15(text: str) -> tuple[int, int]:
    """The character span of PLAN.md section 15: from its '## 15.' line to the next '## ' line."""
    start = text.index("\n## 15.") + 1
    return start, text.index("\n## ", start) + 1


def without_prior_rows(text: str) -> str:
    """``text`` with every A1 and A0 line of section 15 (``- **A1``, ``- **Amendment A1``, the same for A0, with
    their indented continuation lines) removed: the plan as it would read with no A1 or A0 line at all (#59)."""
    start, end = section_15(text)
    kept, dropping = [], False
    for line in text[start:end].splitlines(keepends=True):
        if re.match(r"- \*\*(?:Amendment )?A[01]\b", line):
            dropping = True
            continue
        if dropping and line.startswith("  ") and line.strip():
            continue
        dropping = False
        kept.append(line)
    return text[:start] + "".join(kept) + text[end:]


def plan_with(rows: str, text: str | None = None) -> str:
    """``text`` (default: the stand-in plan without its A1 and A0 lines) with ``rows`` added at the end of section
    15."""
    text = without_prior_rows(stand_in_plan()) if text is None else text
    _, end = section_15(text)
    return text[:end] + rows + text[end:]


def real_folders(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Stand-ins for the pinned real-data folders (results/downvol-steady, data/catalog) and the study folder (the
    tracked RUNLOG and committed copies) in ``tmp_path``, so a real-data run never touches the repo (#48); and a
    stand-in PLAN.md with amendments A1 and A0 written (``PRIOR_ROWS``), so the guards after them are reached (#58)."""
    out, catalog_dir = tmp_path / "results" / "downvol-steady", tmp_path / "data" / "catalog"
    plan = tmp_path / "plan" / "PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(plan_with(PRIOR_ROWS))
    monkeypatch.setattr(S, "DEFAULT_OUT", out)
    monkeypatch.setattr(S, "DEFAULT_CATALOG", catalog_dir)
    monkeypatch.setattr(S, "HERE", tmp_path / "here")
    monkeypatch.setattr(S, "PLAN", plan)
    return out, catalog_dir


def write_snapshot(catalog_dir: Path, bars=S.BARS_SHA256, snapshot_id="snap") -> None:
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / catalog.SNAPSHOT_FILE).write_text(
        json.dumps({"snapshot_id": snapshot_id, "bars_content_sha256": bars})
    )


def write_start(out: Path, k: int, data: str, fast: bool, status: str = "started") -> None:
    path = out / "train" / f"run{k}" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = {"data": data, "fast": fast, "risk_limits": {}}
    path.write_text(json.dumps({"run": k, "status": status, "start": start, "results": {}}))


@pytest.fixture(scope="module")
def train0(tmp_path_factory):
    """One ``run_train.py`` run 0 dry run (synthetic seed 7, fast settings, a copy of config/), clean git."""
    root = tmp_path_factory.mktemp("ts_scripts")
    cfg = copy_config(root / "config")
    out = root / "out"
    before = here_hashes()
    plan = root / "PLAN.md"
    plan.write_text(stand_in_plan())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(S, "PLAN", plan)
        assert RT.main(train_args(out, cfg)) == 0
    return {"root": root, "out": out, "cfg": cfg, "before": before}


@pytest.fixture
def fresh(train0, tmp_path):
    """A private copy of run 0's output folder and config, to change freely."""
    out = tmp_path / "out"
    shutil.copytree(train0["out"], out)
    cfg = copy_config(tmp_path / "config", train0["cfg"])
    return out, cfg


@pytest.fixture
def frozen(fresh, clean_git):
    """A copy of run 0 whose verdict earns the look, frozen."""
    out, cfg = fresh
    set_look_earned(out, True)
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    return out, cfg


# ------------------------------------------------------------------------------------------- pure helpers


def _plan(rows: str, before: str = "", after: str = "") -> str:
    return f"- Branch: R. budget **35%**\n{before}## 15. Amendments\n\n{rows}\n## 17. Code\n{after}"


def test_amendment_row_must_name_the_run():
    """INTERPRETATIONS["amendment_section"] and ["amendment_row"]: section 15 runs from '## 15.' to the next '## '."""
    plan = _plan("- **Amendment run 1 (2026-12-01).** A bug, found by (b).\n- **Amendment run 12** later\n")
    assert S.amendment_row_present(plan, 1) and not S.amendment_row_present(plan, 2)
    assert not S.amendment_row_present(_plan("  - **Amendment run 1** indented\n"), 1)
    row = "- **Amendment run 1 (2026-12-01).** A bug.\n"
    assert not S.amendment_row_present(_plan("", before=row), 1)
    assert not S.amendment_row_present(_plan("", after=row), 1)
    assert not S.amendment_row_present(row, 1)
    assert (
        S.amendments_section("## 15. Amendments\n" + row) == "## 15. Amendments\n" + row
    )  # the last section
    text = stand_in_plan()  # a stand-in with section 14-16 before 15: no amendment run; a row added is found
    assert S.amendment_row_present(text, 1) is False
    assert S.amendments_section(text).startswith(
        "## 15. Amendments"
    ) and "## 17." not in S.amendments_section(text)
    assert S.amendment_row_present(plan_with(row, text), 1)


def test_the_committed_plan_reads_as_a_real_run_will_read_it():
    """The one test that reads the committed PLAN.md (TESTING.md #68), and only what the pre-registration fixes for
    good: its header's branch line reads Branch R at 35% (stop rule 11: the branch never changes after run 0), and its
    section 15 is found from '## 15.' to '## 17.' (not the '## 14-16.' heading before it). Amendments A1 and A0 are not
    read here: their state changes when they are recorded, and the stand-in plans test both states."""
    assert REAL_PLAN == HERE / "PLAN.md" and S.HERE == HERE  # the guards read this study's own plan (#73)
    text = REAL_PLAN.read_text()
    assert S.HERE.name == "downvol-steady" and S.plan_branch(text) == {"branch": "R", "budget_pct": 35}
    section = S.amendments_section(text)
    assert section.startswith("## 15. Amendments") and "\n## " not in section
    assert "## 14-16." in text and "## 14-16." not in section


def test_study_names_plain_params_and_jsonable():
    assert S.study_tag(0, 0) == "downvol-steady-s0" and S.study_tag(1, 2) == "downvol-steady-s1_a2"
    assert S.parse_study("downvol-steady-s1_a2_wf04") == {"seed": 1, "run": 2, "part": "wf04"}
    assert S.parse_study("downvol-steady-s0_final") == {"seed": 0, "run": 0, "part": "final"}
    assert S.parse_study("trend-steady-s0_final") == {"seed": None, "run": None, "part": None}
    p = S.plain_params({"lookback": np.float64(50.0), "target_vol": np.float64(0.6), "crypto_share": 0.4})
    assert p == {"lookback": 50, "target_vol": 0.6, "crypto_share": 0.4} and type(p["lookback"]) is int
    with pytest.raises(ValueError, match="integral"):
        S.plain_params({**p, "lookback": 50.5})
    got = S.jsonable(
        {"a": np.float64("nan"), "b": (np.int64(2), np.bool_(True)), "c": np.arange(2), "e": math.inf}
    )
    assert got == {"a": None, "b": [2, True], "c": [0, 1], "e": None}
    assert S.point(True, 1.0) is True and S.point(False, 1.0) is False and S.point(True, math.nan) is None
    assert [S.status(v) for v in (True, False, None)] == ["PASS", "FAIL", "MISSING"]
    assert S.offsets_of("all", 6) == [1, 2, 3, 4, 5] and S.offsets_of([3, 1], 6) == [3, 1]
    assert S.offsets_of("guarded", 260) == list(range(53, 260))


def test_the_pinned_values_are_the_plan_s():
    assert (S.TRAIN_LAST_CLOSE, S.VALIDATE_LAST_CLOSE) == (
        pd.Timestamp("2023-01-01", tz="UTC"),
        pd.Timestamp("2024-07-01", tz="UTC"),
    )
    assert S.ROWS == {
        "train": {"KRAKEN": 2190, "BINANCE": 1963},
        "validate": {"KRAKEN": 2737, "BINANCE": 2510},
    }
    assert S.PANEL_SHA256 == {
        "KRAKEN": "355aabe22c8a9a8173db6bd954cb7a8c43dd65b2211c04bfe21f509a4572ebc6",
        "BINANCE": "2c1a42572f08935523f6edf284edf3bd44d8d8f5bc2293a36693f3aeb6c57587",
    }
    assert S.BARS_SHA256 == "08f5ca2ca56dbba2526673bcf3515e25ca6d097da4c91b6c08e492ae21b3cd1e"
    assert (S.SEEDS, S.FOLD_SEED_STEP, S.FINAL_SEED_OFFSET, S.STABLE_K) == ({"A": 0, "B": 1}, 1000, 5000, 10)
    assert (S.STRICT_EXTRA, S.K4_AS_15, S.MAX_AMENDMENTS) == (49, 14, 2)
    assert (
        S.PRIOR_TRIALS == 2400 and S.PINNED["prior_trials"] == 2400
    )  # section 14: vol-steady run 0's trials (W1)
    assert S.PINNED["down_factor"] == 2.0 and "q-only" in S.PINNED["e1_null"]
    assert {"measure", "e1_q_only", "e1_whole", "strict_count"} <= set(S.INTERPRETATIONS)
    assert (
        not hasattr(S, "STOP_EXTRA") and "stop_levels" not in S.PINNED
    )  # no stop-loss variant (section 11A)
    assert (S.KEPT_ROWS, S.W_KRAKEN, S.W_BINANCE, S.W_VALIDATE, S.VALIDATE_KEPT) == (1820, 260, 208, 78, 546)
    assert S.R4_BOOKS == (100.0, 500.0, 2500.0, 10_000.0, 50_000.0)
    assert S.PLAN_SETTINGS == S.Settings(200, 10_000, 5000, 1000, 200, 20)
    assert S.PINNED["settings"]["n_trials"] == 200 and S.PINNED["budgets_minutes"] == {
        "run": 60,
        "controls": 120,
    }
    assert (S.BRANCH, S.BUDGET_PCT, S.RISK_SHA256_QUOTED[:8]) == ("R", 35, "d3f58253")
    assert S.PINNED["allowed_s"] == [0.30, 0.40, 0.50, 0.60] and S.PINNED["first_active_row"] == 15
    assert S.PINNED["quarters"] == [0.0, 0.25, 0.5, 0.75, 1.0] and S.PINNED["q_tol"] == 1e-9
    assert S.PINNED["specs"][1] == {
        "name": "target_vol",
        "kind": "float",
        "low": 0.3,
        "high": 1.2,
        "log": True,
        "choices": (),
    }
    assert S.A0_VOL_POINT == {"lookback": 30, "target_vol": 0.60, "crypto_share": 0.50}
    assert (S.A0_PANELS, S.A0_VOL_PANELS, S.A0_ALARM_FP, S.A0_POWER_MIN) == (20, 200, 3, 4)
    assert S.TRIGGERS == ("a", "b", "c", "other, after the verdict")


def test_the_run_count_table_by_hand():
    """Stop rule 17's table (VP's, with E1-whole's 2 x 207 whole-schedule shifts added), part by part."""
    parts = S.RUN_PARTS
    seeds, folds, w = 2, 5, 260
    run = (
        seeds * folds * 2  # walk_forward_optimize's IS and OOS runs
        + seeds * folds * 5  # S, S at 2x, N0, N0 at 2x, X
        + seeds * w  # R_0 and its 259 q-only shifts
        + seeds * 207  # E1-whole: the guarded whole-schedule shifts (a description)
        + seeds * 6 * folds  # G5(a)
        + 3  # theta_final in-sample (2) and its 2x check
        + 4 * 2
        + 4 * folds  # grid at 1x and 2x, grid N0
        + 6  # G5(b)
        + 4 * folds * 2
        + 4 * folds
        + 4 * 208  # S(s_k) 1x, 2x, N0, R_0 and 207 shifts
        + 6 * folds
        + folds  # check days, daily
        + 4  # R4
        + 4
        + 4
        + 156  # Binance S, N0, R_0 and 155 shifts
        + 2 * folds
        + 1  # B1, B2, N0-span
    )
    boots = 2 + 4 + 1 + 4 + 1 + 5
    assert set(parts) == {"study", "run", "bootstrap"} and sum(parts["run"].values()) == run == 1793 + 414
    assert S.run_counts() == {"study": 12, "run": run, "bootstrap": boots + 60}
    assert S.a0_counts() == {"study": 200, "run": 40 * (10 + 208) + 200 * 209, "bootstrap": 40}
    timing = {"seconds": {"study": 6.0, "run": 0.013, "bootstrap": 1.5}}
    got = S.projection(timing, S.run_counts(), 60)
    by_hand = (12 * 6.0 + run * 0.013 + (boots + 60) * 1.5) / 60
    assert got["cpu_minutes"] == pytest.approx(by_hand, rel=1e-12) and got["allows"] == (by_hand <= 60)
    assert S.projection({"seconds": {"study": 300.0, "run": 0, "bootstrap": 0}}, S.run_counts(), 60)[
        "allows"
    ]  # 12 x 300 s = exactly 60 CPU-minutes starts
    assert not S.projection({"seconds": {"study": 300.001, "run": 0, "bootstrap": 0}}, S.run_counts(), 60)[
        "allows"
    ]


def test_the_branch_line_and_the_branch_guard(tmp_path):
    """Stop rule 11: Branch R, the budget 35 as quoted, min_cash 0.20, max_coin 0.60 and the coins; another file
    hash with the same values is recorded, not refused."""
    plan = stand_in_plan()
    assert S.plan_branch(plan) == {"branch": "R", "budget_pct": 35}  # the header's line, as the plan words it
    assert S.plan_branch("- **Branch: F** fixed\n") == {"branch": "F", "budget_pct": None}
    assert S.plan_branch("- Branch: F. fixed **30%**\n") == {"branch": "F", "budget_pct": 30}
    for bad in ("~~**Branch F (fixed settings)**~~\n", "  - Branch: R. **35%**\n", "- Branch: RF **35%**\n"):
        with pytest.raises(S.Refusal, match="no '- Branch: ' line"):
            S.plan_branch(bad)
    cfg = copy_config(tmp_path / "config")
    ok = S.check_branch(sd.steady_limits(cfg), plan)
    assert ok["branch"] == "R" and ok["sha256_as_quoted"] is True
    with pytest.raises(S.Refusal, match="runs Branch R only"):
        S.check_branch(sd.steady_limits(cfg), "- Branch: F. budget **35%**\n")
    with pytest.raises(S.Refusal, match="quotes a budget of 30%"):
        S.check_branch(sd.steady_limits(cfg), "- Branch: R. budget **30%**\n")
    for i, (old, new) in enumerate(
        (
            ("max_drawdown_budget_pct: 35", "max_drawdown_budget_pct: 30"),
            ("min_cash_pct: 20", "min_cash_pct: 25"),
            ("max_coin_pct: 60", "max_coin_pct: 55"),
        )
    ):
        other = copy_config(tmp_path / f"c{i}")
        edit_steady_entry(other, old, new)
        with pytest.raises(S.Refusal, match="stop rule 11"):
            S.check_branch(sd.steady_limits(other), plan)
    tbd = copy_config(tmp_path / "tbd")
    set_steady_budget(tbd, "TBD")
    with pytest.raises(S.Refusal, match="stop rule 11"):
        S.check_branch(sd.steady_limits(tbd), plan)
    same = copy_config(tmp_path / "same")
    (same / "risk_levels.yaml").write_text((same / "risk_levels.yaml").read_text() + "# a comment\n")
    got = S.check_branch(sd.steady_limits(same), plan)
    assert got["sha256_as_quoted"] is False and got["risk_levels_sha256"] == S.sha256_file(
        same / "risk_levels.yaml"
    )


def test_the_config_hash_covers_section_14_s_files(tmp_path, monkeypatch):
    paths = S.frozen_paths()
    named = ["research/downvol-steady/PLAN.md", *(f"research/downvol-steady/{f}" for f in S.SCRIPTS)]
    named += [
        f"lab/runner/{f}"
        for f in (
            "downvol.py",
            "volsteady.py",
            "trend.py",
            "portfolio.py",
            "reference.py",
            "interface.py",
            "steady.py",
        )
    ]
    named += [f"lab/data/{f}" for f in ("panel.py", "catalog.py", "external.py", "futures.py", "loaders.py")]
    named += ["lab/data/sources.py", "lab/data/synthetic.py", "lab/config.py"]
    named += ["lab/__init__.py", "lab/data/__init__.py", "lab/runner/__init__.py"]
    named += [
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
    assert "lab/runner/holdmix.py" not in paths  # nothing on the real-run path imports it
    assert not any(p.endswith(("RESULTS.md", "RUNLOG.jsonl", "FROZEN.json")) for p in paths)
    assert not any(p.startswith("research/vol-steady/") for p in paths)  # VP's files are not this study's
    cfg = copy_config(tmp_path / "config")
    hashes = S.file_hashes(cfg)
    assert hashes == S.file_hashes() and hashes["lab/data/external.py"] == S.sha256_file(
        S.REPO / "lab/data/external.py"
    )
    base = S.config_hash(hashes)
    for rel in (
        "lab/data/external.py",
        "lab/runner/downvol.py",
        "lab/runner/volsteady.py",
        "lab/runner/trend.py",
        "research/downvol-steady/PLAN.md",
    ):
        assert S.config_hash({**hashes, rel: "0" * 64}) != base  # a change to any hashed file moves it
    (cfg / "costs.yaml").write_text((cfg / "costs.yaml").read_text() + "# changed\n")
    changed = S.file_hashes(cfg)
    assert [k for k in hashes if hashes[k] != changed[k]] == ["config/costs.yaml"]
    monkeypatch.setitem(S.PINNED, "lead_guard", 51)
    assert S.config_hash(hashes) != base  # the pinned values are hashed too


def test_the_hashed_list_holds_every_lab_module_the_scripts_import():
    """M14: a new import on the real-run path cannot escape the config hash."""
    code = (
        "import importlib.util, sys, json\n"
        f"here = {str(HERE)!r}\n"
        "for n, f in (('downvol_steady_run_train', 'run_train.py'), ('downvol_steady_freeze', 'freeze.py'), "
        "('downvol_steady_run_validate', 'run_validate.py')):\n"
        "    spec = importlib.util.spec_from_file_location(n, here + '/' + f)\n"
        "    m = importlib.util.module_from_spec(spec); sys.modules[n] = m; spec.loader.exec_module(m)\n"
        "print(json.dumps(sorted(getattr(m, '__file__', '') for k, m in sys.modules.items() "
        "if (k == 'lab' or k.startswith('lab.')) and getattr(m, '__file__', None))))\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=S.REPO, check=True)
    files = [Path(f).resolve().relative_to(S.REPO).as_posix() for f in json.loads(res.stdout)]
    assert files and set(files) <= set(S.frozen_paths()), sorted(set(files) - set(S.frozen_paths()))
    assert (
        "lab/runner/downvol.py" in files
        and "lab/runner/volsteady.py" in files
        and "lab/runner/trend.py" in files
        and "lab/data/external.py" in files
    )


def test_compare_hashes_and_the_risk_levels_exception(tmp_path, monkeypatch):
    cfg = copy_config(tmp_path / "config")
    rec = S.file_hashes(cfg)
    rec_hash = S.config_hash(rec)
    limits = sd.steady_limits(cfg)
    assert S.compare_hashes(rec, rec_hash, S.file_hashes(cfg), limits, cfg) == {
        "ok": True,
        "differs": [],
        "exception": None,
    }
    edit_steady_entry(cfg, "hold_mix_max_rebalances_per_30d: 2", "hold_mix_max_rebalances_per_30d: 3")
    got = S.compare_hashes(rec, rec_hash, S.file_hashes(cfg), limits, cfg)
    assert got["ok"] and got["differs"] == [S.RISK_FILE] and "never rescored" in got["exception"]["g6"]
    assert got["exception"]["risk_levels_sha256_now"] == S.sha256_file(cfg / "risk_levels.yaml")
    (cfg / "costs.yaml").write_text((cfg / "costs.yaml").read_text() + "# changed\n")
    got = S.compare_hashes(rec, rec_hash, S.file_hashes(cfg), limits, cfg)
    assert not got["ok"] and got["differs"] == ["config/costs.yaml", S.RISK_FILE]
    for i, (old, new, why) in enumerate(
        (
            ("min_cash_pct: 20", "min_cash_pct: 25", "changed its coins, min_cash or max_coin"),
            ("max_coin_pct: 60", "max_coin_pct: 55", "changed its coins, min_cash or max_coin"),
            ("coins: [BTC, ETH, USDC]", "coins: [BTC, USDC]", "no longer reads"),
        )
    ):
        other = copy_config(tmp_path / f"case{i}")
        edit_steady_entry(other, old, new)
        got = S.compare_hashes(rec, rec_hash, S.file_hashes(other), limits, other)
        assert not got["ok"] and got["differs"] == [S.RISK_FILE] and why in got["reason"]
    monkeypatch.setitem(S.PINNED, "lead_guard", 51)
    got = S.compare_hashes(rec, rec_hash, rec, limits, cfg)
    assert not got["ok"] and got["differs"] == ["<pinned values>"]


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
    assert not S.git_state(repo)["dirty"]
    (repo / "ignored").mkdir()
    (repo / "ignored" / "x.txt").write_text("x\n")
    assert not S.git_state(repo)["dirty"]
    (repo / "new").mkdir()
    (repo / "new" / "b.txt").write_text("b\n")
    state = S.git_state(repo)
    assert state["dirty"] and state["changes"] == ["?? new/b.txt"]
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RuntimeError, match="git rev-parse HEAD failed"):
        S.git_state(plain)


def test_check_out_dir_and_check_real_paths_by_hand(tmp_path):
    for inside in (
        S.DEFAULT_OUT,
        S.DEFAULT_OUT / "x",
        S.REPO,
        S.REPO / "scratch",
        S.REPO / "results" / "other",
    ):
        with pytest.raises(S.Refusal, match="never writes into"):
            S.check_out_dir(inside)
    S.check_out_dir(tmp_path / "scratch")
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
    assert S.runlog_path(tmp_path, synthetic=False) == HERE / "RUNLOG.jsonl"
    assert S.tracked_dir(tmp_path, synthetic=False) == HERE
    assert S.runlog_path(tmp_path, synthetic=True) == tmp_path / "RUNLOG.jsonl"
    assert S.tracked_dir(tmp_path, synthetic=True) == tmp_path / "tracked"
    assert (
        S.DEFAULT_OUT == S.REPO / "results" / "downvol-steady"
        and S.DEFAULT_CATALOG == S.REPO / "data" / "catalog"
    )


def test_read_snapshot_stops_on_another_bars_hash(tmp_path):
    assert S.read_snapshot(tmp_path, synthetic=True) == {
        "snapshot_id": "synthetic",
        "bars_content_sha256": "synthetic",
    }
    with pytest.raises(S.Refusal, match="cannot read"):
        S.read_snapshot(tmp_path, synthetic=False)
    write_snapshot(tmp_path, bars="0" * 64)
    with pytest.raises(S.Refusal, match="stop rule 2"):
        S.read_snapshot(tmp_path, synthetic=False)
    write_snapshot(tmp_path)
    assert S.read_snapshot(tmp_path, synthetic=False) == {
        "snapshot_id": "snap",
        "bars_content_sha256": S.BARS_SHA256,
    }


def test_the_synthetic_panels_have_the_plan_s_rows_and_dates(tmp_path):
    load = partial(
        S.load_study_panel, catalog_dir=tmp_path, config_dir=None, loader=S.synthetic_bar_loader(SEED)
    )
    k_train, b_train = load(S.SOURCE, S.TRAIN_LAST_CLOSE), load(S.ROBUSTNESS, S.TRAIN_LAST_CLOSE)
    k_val, b_val = load(S.SOURCE, S.VALIDATE_LAST_CLOSE), load(S.ROBUSTNESS, S.VALIDATE_LAST_CLOSE)
    assert (len(k_train), len(b_train), len(k_val), len(b_val)) == (2190, 1963, 2737, 2510)
    assert k_train.index.equals(T.train_grid())  # appendix B's grid, 2018-01-13 dropped
    assert b_train.index[0] == pd.Timestamp("2017-08-18", tz="UTC")
    assert sd.panel_hash(k_val.iloc[:2190]) == sd.panel_hash(k_train)
    assert sd.panel_hash(b_val.iloc[:1963]) == sd.panel_hash(b_train)
    w = RV.validate_window(k_val.index)
    assert (w.first_h120, w.t0, w.last) == tuple(
        pd.Timestamp(d, tz="UTC") for d in ("2017-01-02", "2023-01-02", "2024-07-01")
    )
    assert len(k_val.loc[w.t0 : w.last]) - 1 == S.VALIDATE_KEPT
    path = D.downvol_path(k_val, 30, 0.6, 0.5)
    steps = RV.validate_steps(k_val.index, w, path.z, path.share, path.q, 0.5)
    sched = steps.schedule
    assert len(sched.checks) == 78 and k_val.index[sched.checks[-1]] == pd.Timestamp("2024-06-24", tz="UTC")
    assert len(steps.q) == len(steps.s) == 78 and np.array_equal(sched.share, 0.5 * steps.q)
    windows = S.windows_of(k_train.index)
    assert [w.t0 for w in windows] == [k_train.index[r] for r in (365, 730, 1095, 1460, 1825)]


def test_load_study_panel_never_asks_for_the_test_window(tmp_path, monkeypatch):
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
    K = S.load_study_panel(
        S.SOURCE,
        S.VALIDATE_LAST_CLOSE,
        catalog_dir=tmp_path,
        config_dir=None,
        loader=S.synthetic_bar_loader(SEED),
    )
    monkeypatch.setattr(
        S,
        "load_panel",
        lambda source, interval, *, last_close, **kw: K.loc[: last_close + pd.Timedelta(days=1)],
    )
    with pytest.raises(HoldoutWindowError, match="a close after"):
        S.load_study_panel(S.SOURCE, S.TRAIN_LAST_CLOSE, catalog_dir=tmp_path, config_dir=None, loader=None)


# ------------------------------------------------------------------------------- run_train start guards


def test_a_dirty_tree_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(DIRTY))
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"
    assert RT.main(train_args(out, cfg)) == 2
    assert "the git tree is dirty" in capsys.readouterr().err and not out.exists()
    real_folders(monkeypatch, tmp_path)  # real data too, in the pinned (here: stand-in) folders
    assert RT.main([]) == 2
    assert "the git tree is dirty" in capsys.readouterr().err and not S.DEFAULT_OUT.exists()


def test_dry_run_switches_are_refused_on_real_data(tmp_path, capsys):
    for flag in ("--fast", "--allow-dirty"):
        assert RT.main(["--out-dir", str(tmp_path / "out"), flag]) == 2
        assert "synthetic dry runs only" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_run_0_runs_once_and_takes_no_trigger(tmp_path, clean_git, capsys):
    out = tmp_path / "out"
    cfg = copy_config(tmp_path / "config")
    assert RT.main(train_args(out, cfg, "--trigger", "b")) == 2
    assert "for amendment runs only" in capsys.readouterr().err and not out.exists()
    (out / "train").mkdir(parents=True)
    assert RT.main(train_args(out, cfg)) == 2
    assert "run 0 runs once" in capsys.readouterr().err and list((out / "train").iterdir()) == []


@pytest.mark.parametrize(
    "k, match", [("0", "run 0 is run without --amendment"), ("3", "INCONCLUSIVE"), ("-1", "numbered 1..2")]
)
def test_amendment_numbers_outside_1_and_2_are_refused(tmp_path, clean_git, capsys, k, match):
    out = tmp_path / "out"
    (out / "train" / "run0").mkdir(parents=True)
    (out / "train" / "run0" / "summary.json").write_text("{}")
    assert RT.main(train_args(out, copy_config(tmp_path / "config"), "--amendment", k, "--trigger", "b")) == 2
    assert match in capsys.readouterr().err


def test_an_amendment_run_needs_the_previous_start_a_fresh_name_and_a_trigger(tmp_path, clean_git, capsys):
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"
    train = out / "train"
    (train / "run0").mkdir(parents=True)
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "b")) == 2
    assert "run0/summary.json does not exist" in capsys.readouterr().err
    write_start(out, 0, "synthetic", True)
    for trigger in ([], ["--trigger", "d"], ["--trigger", "other"]):  # stop rule 18: a recorded trigger
        assert RT.main(train_args(out, cfg, "--amendment", "1", *trigger)) == 2
        assert "needs --trigger" in capsys.readouterr().err
    (train / "run1").mkdir()
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "a")) == 2
    assert "is never resumed" in capsys.readouterr().err
    (train / "run1").rmdir()
    (train / "downvol-steady-s1_a1_wf02").mkdir()
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "a")) == 2
    assert "studies of amendment run 1 exist" in capsys.readouterr().err
    assert sorted(p.name for p in train.iterdir()) == ["downvol-steady-s1_a1_wf02", "run0"]


def test_an_amendment_run_continues_the_same_kind_of_run(tmp_path, clean_git, capsys):
    cfg = copy_config(tmp_path / "config")
    for i, (runs, message) in enumerate(
        (([("real", False)], "run 0 was a real run"), ([("synthetic", False)], "(fast False)"))
    ):
        out = tmp_path / f"o{i}"
        for j, (data, fast) in enumerate(runs):
            write_start(out, j, data, fast)
        assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "c")) == 2
        assert message in capsys.readouterr().err and not (out / "train" / "run1").exists()
    out = tmp_path / "o9"
    (out / "train" / "run0").mkdir(parents=True)
    (out / "train" / "run0" / "summary.json").write_text("{}")
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "c")) == 2
    assert "cannot read run 0's start record" in capsys.readouterr().err


def test_a_real_amendment_run_needs_its_plan_row(tmp_path, clean_git, monkeypatch, capsys):
    out, _ = real_folders(monkeypatch, tmp_path)
    write_start(out, 0, "real", fast=False)
    plan = tmp_path / "PLAN.md"
    plan.write_text(_plan("- **M26.** no amendment run row\n" + PRIOR_ROWS))
    monkeypatch.setattr(S, "PLAN", plan)
    before = here_hashes()
    assert RT.main(["--amendment", "1", "--trigger", "b"]) == 2
    assert "no '- **Amendment run 1' row" in capsys.readouterr().err
    plan.write_text(_plan("- **Amendment run 1 (2026-12-01).** Bug, (b), test.\n" + PRIOR_ROWS))
    assert RT.main(["--amendment", "1", "--trigger", "b"]) == 2  # past the row check: no SNAPSHOT.json here
    assert "SNAPSHOT.json" in capsys.readouterr().err
    assert not (out / "train" / "run1").exists() and here_hashes() == before


def test_the_branch_guard_refuses_before_anything_is_written(tmp_path, clean_git, capsys):
    cfg = copy_config(tmp_path / "config")
    set_steady_budget(cfg, "30")
    out = tmp_path / "out"
    assert RT.main(train_args(out, cfg)) == 2
    assert "stop rule 11" in capsys.readouterr().err and not out.exists()


def test_a_run_reads_the_branch_from_its_plan(tmp_path, clean_git, monkeypatch, capsys):
    """Stop rule 11 at run level: run_train.py reads the branch line from the plan it runs under (``S.PLAN``), so a
    plan whose header says Branch F, or quotes 30%, stops a dry run and a real run before anything is written, with
    config/ at 35% (#73). The re-timing and the run itself are stubbed, so a guard that ignores the plan fails at
    once (exit 3) instead of starting a run; the same real run under the plan's own branch line gets past it."""
    monkeypatch.setattr(S, "measure_timing", quick_timing())

    def stop(args, summary, run_dir, ctx, settings):
        raise S.Stop("the branch guard let the run start")

    monkeypatch.setattr(RT, "train_phase", stop)
    good = "- Branch: R. Steady drawdown budget **35%**"
    bad_lines = {
        "- Branch: F. Steady drawdown budget **35%**": "PLAN.md's branch is F",
        "- Branch: R. Steady drawdown budget **30%**": "quotes a budget of 30%",
    }
    assert good in BRANCH_LINE
    cfg = copy_config(tmp_path / "config")
    plan = tmp_path / "bad" / "PLAN.md"
    plan.parent.mkdir()
    monkeypatch.setattr(S, "PLAN", plan)
    for i, (bad, message) in enumerate(bad_lines.items()):
        plan.write_text(stand_in_plan().replace(good, bad))
        out = tmp_path / f"out{i}"
        assert RT.main(train_args(out, cfg)) == 2
        err = capsys.readouterr().err
        assert "stop rule 11" in err and message in err and not out.exists()
    out, catalog_dir = real_folders(monkeypatch, tmp_path)
    write_snapshot(catalog_dir)
    for bad, message in bad_lines.items():
        S.PLAN.write_text(plan_with(PRIOR_ROWS, without_prior_rows(stand_in_plan()).replace(good, bad)))
        assert RT.main([]) == 2
        err = capsys.readouterr().err
        assert "stop rule 11" in err and message in err
        assert not out.exists() and not (tmp_path / "here").exists()
    S.PLAN.write_text(plan_with(PRIOR_ROWS))
    assert RT.main([]) == 3
    assert "the branch guard let the run start" in capsys.readouterr().err
    assert summary(out)["start"]["branch"]["branch"] == "R"


def test_stop_rule_12_refuses_a_target_set_the_limits_refuse(tmp_path, clean_git, monkeypatch, capsys):
    """Feasibility before data (stop rule 12, every s x q): with a tighter coin cap (the branch guard bypassed here,
    since it pins max_coin at 0.60), the 0.72 plateau extreme (0.36 a coin) breaks the limits and the run refuses."""
    cfg = copy_config(tmp_path / "config")
    edit_steady_entry(cfg, "max_coin_pct: 60", "max_coin_pct: 37")
    monkeypatch.setattr(S, "check_branch", lambda limits, text: {"branch": "R", "budget_pct": 35})
    out = tmp_path / "out"
    assert RT.main(train_args(out, cfg)) == 2
    err = capsys.readouterr().err
    assert "stop rule 12" in err and "0.72" in err and not out.exists()


def test_the_projection_guard(tmp_path, clean_git, monkeypatch, capsys):
    """Stop rule 17: above 60 CPU-minutes a real run refuses with nothing written; exactly 60 starts (and records
    its timing and projection before any bar); a dry run records a projection above the budget and never refuses;
    a timing that raises refuses."""
    out, catalog_dir = real_folders(monkeypatch, tmp_path)
    write_snapshot(catalog_dir)
    exactly = {"study": 300.0, "run": 0.0, "bootstrap": 0.0}  # 12 x 300 s = 60 CPU-minutes
    monkeypatch.setattr(S, "measure_timing", quick_timing({**exactly, "study": 300.001}))
    assert RT.main([]) == 2
    assert "stop rule 17" in capsys.readouterr().err
    assert not out.exists() and not (tmp_path / "here").exists()  # no RUNLOG line, no run number used up
    monkeypatch.setattr(S, "measure_timing", quick_timing(exactly))

    def stop(args, summary, run_dir, ctx, settings):
        raise S.Stop("enough")

    monkeypatch.setattr(RT, "train_phase", stop)
    assert RT.main([]) == 3
    s = summary(out)
    assert s["start"]["projection"] == {"cpu_minutes": 60.0, "budget_minutes": 60, "allows": True}
    assert s["start"]["timing"]["seconds"] == exactly and s["start"]["run_counts"] == S.run_counts()
    assert [x["run"] for x in S.runlog_entries(tmp_path / "here" / "RUNLOG.jsonl")] == [0]
    monkeypatch.setattr(S, "measure_timing", quick_timing({**exactly, "study": 1e6}))
    dry = tmp_path / "dry"
    assert RT.main(train_args(dry, copy_config(tmp_path / "config"))) == 3
    assert summary(dry)["start"]["projection"]["allows"] is False

    def broken(*args):
        raise ValueError("the engine broke")

    monkeypatch.setattr(S, "measure_timing", broken)
    assert RT.main(train_args(tmp_path / "dry2", copy_config(tmp_path / "config2"))) == 2
    assert "the re-timing failed" in capsys.readouterr().err and not (tmp_path / "dry2").exists()


def test_real_runs_use_the_pinned_folders_only(tmp_path, clean_git, monkeypatch, capsys):
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
    assert (
        RT.main(["--config-dir", str(S.REPO / "config")]) == 2
    )  # config/ itself passes; no SNAPSHOT.json here
    assert "SNAPSHOT.json" in capsys.readouterr().err and not out.exists()
    for folder in (out, elsewhere):
        write_start(folder, 0, "real", False, status="complete")
    assert FZ.main(["--config-dir", str(cheap)]) == 2
    assert "--config-dir" in capsys.readouterr().err
    assert FZ.main(["--out-dir", str(elsewhere)]) == 2
    assert "--out-dir" in capsys.readouterr().err


def test_a_dry_run_never_writes_into_the_study_folder_or_the_repo(
    train0, tmp_path, clean_git, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    default = repo / "results" / "downvol-steady"
    monkeypatch.setattr(S, "REPO", repo)
    monkeypatch.setattr(S, "DEFAULT_OUT", default)
    cfg = copy_config(tmp_path / "config")
    for out in (default, repo / "scratch"):
        assert RT.main(train_args(out, cfg)) == 2
        assert "never writes into" in capsys.readouterr().err and not out.exists()
    shutil.copytree(train0["out"], default)
    set_look_earned(default, True)
    before = S.tree_hashes(default)
    # each call is refused by its own folder guard, read call by call: the look's would otherwise be hidden behind
    # its later "run freeze.py first" refusal (#73)
    for call in (
        lambda: RT.main(train_args(default, cfg, "--amendment", "1", "--trigger", "b")),
        lambda: FZ.main(["--out-dir", str(default), "--config-dir", str(cfg)]),
        lambda: RV.main(validate_args(default, cfg)),
        lambda: A0.main(["--out-dir", str(repo / "scratch")]),
        lambda: A1.main(["--out-dir", str(repo / "scratch")]),
    ):
        assert call() == 2
        assert "never writes into" in capsys.readouterr().err
    assert S.tree_hashes(default) == before and not (default / "validate").exists()


def test_the_runlog_keeps_a_deleted_run_or_look_from_running_again(tmp_path, clean_git, monkeypatch, capsys):
    out, catalog_dir = real_folders(monkeypatch, tmp_path)
    here = tmp_path / "here"
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
    assert not out.exists() and S.runlog_entries(tmp_path / "none.jsonl") == []


# -------------------------------------------------------------------------------- run_train, the run


def test_the_start_record_and_the_runlog_come_before_any_bar(tmp_path, clean_git, monkeypatch, fast_timing):
    cfg = copy_config(tmp_path / "config")
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
    assert start["branch"]["branch"] == "R" and start["branch"]["budget_pct"] == 35
    assert (
        start["risk_limits"]["max_drawdown_budget"] == 0.35
        and start["g6_budget"]["max_drawdown_budget"] == 0.35
    )
    assert start["risk_limits"]["sha256"] == S.sha256_file(cfg / "risk_levels.yaml")
    assert start["feasible_shares"] == V.check_feasibility(sd.steady_limits(cfg))
    every = sorted({s * q for s in (0.24, 0.30, 0.40, 0.50, 0.60, 0.72) for q in (0.0, 0.25, 0.5, 0.75, 1.0)})
    assert start["feasible_shares"] == every and len(every) == 22  # 30 products, 8 of them repeats
    assert (
        start["git"] == CLEAN and start["data"] == "synthetic" and start["fast"] and start["trigger"] is None
    )
    assert start["projection"]["allows"] and start["run_counts"] == S.run_counts()
    line = json.loads(seen["runlog"][0])
    assert len(seen["runlog"]) == 1 and line["run"] == 0 and line["config_hash"] == start["config_hash"]
    after = summary(out)
    assert after["status"] == "stopped: Stop: enough" and after["start"] == seen["summary"]["start"]


def _leaky(original):
    def factory(seed):
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

    return factory


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


@pytest.mark.parametrize(
    "wrap, message",
    [
        (_leaky, "stopped: HoldoutWindowError"),
        (_drop_close("BTC/USD.KRAKEN", "2019-06-01"), "stop rule 2: KRAKEN has 2189 train rows"),
        (_drop_close("ETHUSDT.BINANCE", "2019-06-01"), "stop rule 2: BINANCE has 1962 train rows"),
    ],
)
def test_the_data_stops(tmp_path, clean_git, monkeypatch, fast_timing, wrap, message):
    """Stop rule 5 (a bar after 2024-07-01 00:00 UTC) and stop rule 2 (a row count), recorded with the panels."""
    monkeypatch.setattr(S, "synthetic_bar_loader", wrap(S.synthetic_bar_loader))
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    s = summary(out)
    assert s["status"].startswith(message) or message in s["status"], s["status"]
    assert not (out / "train" / "run0" / "trials.parquet").exists()


def test_another_snapshot_or_real_panels_with_other_bars_stop_the_run(
    tmp_path, clean_git, monkeypatch, fast_timing
):
    monkeypatch.setattr(
        S,
        "read_snapshot",
        lambda catalog_dir, synthetic: {"snapshot_id": "another", "bars_content_sha256": "x"},
    )
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    assert "is not the one SNAPSHOT.json names" in summary(out)["status"]
    # a real run (stand-in folders) whose panels are not the pinned ones (synthetic bars stand in for the catalog)
    monkeypatch.undo()
    monkeypatch.setattr(catalog, "load_bars", _refuse_real_bars)
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
    monkeypatch.setattr(S, "measure_timing", quick_timing())
    real, catalog_dir = real_folders(monkeypatch, tmp_path / "r")
    write_snapshot(catalog_dir, snapshot_id="synthetic")
    original = S.load_study_panel
    monkeypatch.setattr(
        S,
        "load_study_panel",
        lambda source, last, **kw: original(source, last, **{**kw, "loader": S.synthetic_bar_loader(SEED)}),
    )
    assert RT.main([]) == 3
    assert "does not hash to 355aabe2" in summary(real)["status"]


def test_a_crash_is_recorded_and_raised(tmp_path, clean_git, monkeypatch, fast_timing):
    def broken(seed):
        def loader(*args, **kwargs):
            raise KeyError("boom")

        return loader

    monkeypatch.setattr(S, "synthetic_bar_loader", broken)
    out = tmp_path / "out"
    with pytest.raises(KeyError):
        RT.main(train_args(out, copy_config(tmp_path / "config")))
    assert summary(out)["status"].startswith("crashed: KeyError")


def test_a_changed_start_record_stops_the_run_and_is_recorded(tmp_path, clean_git, monkeypatch, fast_timing):
    def tampering(args, summary, run_dir, ctx, settings):
        summary["start"]["utc"] = "changed"
        return {}

    monkeypatch.setattr(RT, "train_phase", tampering)
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    assert summary(out)["status"] == "stopped: Stop: the start fields changed during the run"


# ---------------------------------------------------------------------- the bundles' consistency stops


LIMITS = {"min_cash": 0.20, "max_coin": 0.60}


@pytest.fixture(scope="module")
def walk():
    """A random walk on the train grid with fixed fold params: cheap bundles for the consistency-stop tests."""
    panel = T.random_walk_panel(3)
    windows = S.windows_of(panel.index)
    params = [{"lookback": 30, "target_vol": 0.8, "crypto_share": s} for s in (0.3, 0.6, 0.5, 0.4, 0.5)]
    return panel, windows, params


def bundle(walk, **kw):
    panel, windows, params = walk
    c1 = Costs.from_yaml()
    return S.plain_bundle(
        panel,
        windows,
        params,
        limits=LIMITS,
        costs1=c1,
        costs2=c1.stressed(),
        **{"offsets": [53, 200], "whole": [53], **kw},
    )


def _stressed_run_span(original, only=None):
    def run_span(bars, schedule, *, costs, **kw):
        if only is None or only(kw):
            costs = costs.stressed()
        return original(bars, schedule, costs=costs, **kw)

    return run_span


def _nudged(original):
    def run_span(*args, **kw):
        res = original(*args, **kw)
        res.loc[res.index[400], "ret"] += 1e-12  # a fold-0 kept row, after t0
        return res

    return run_span


def _stressed_q_shift(original):
    def run_q_shift(bars, steps, *, costs, **kw):
        return original(bars, steps, costs=costs.stressed(), **kw)

    return run_q_shift


def test_the_plain_bundle_s_comparators_match_s_and_its_checks_stop(walk, monkeypatch):
    b = bundle(walk)
    panel, windows, params = walk
    assert (
        b["W"] == 260
        and len(b["S"]) == 1820
        and set(b["shifts"]) == {53, 200}
        and set(b["whole_shifts"]) == {53}
    )
    assert np.array_equal(
        b["R0"].loc[b["runs"][0].index[366:]].to_numpy(), S.kept_of(b["runs"][0], windows[0].t0).to_numpy()
    )
    head = b["schedule"].head_share  # fold 0's share row by row before c_0 (INTERPRETATIONS["schedule_head"])
    assert np.array_equal(head, b["runs"][0].attrs["share"][: len(head)]) and len(set(head.tolist())) > 1
    # E1's shifts are the q-only shifts (M1): each check keeps its fold's s; E1-whole's move s with q (VP's)
    steps, c1 = b["steps"], Costs.from_yaml()
    assert steps.schedule is b["schedule"] and steps.s.tolist() == [
        params[i]["crypto_share"] for i in b["schedule"].fold
    ]
    for u in (53, 200):
        q_only = (
            D.run_q_shift(b["span"], steps, limits=LIMITS, costs=c1, u=u)["ret"].loc[b["S"].index].to_numpy()
        )
        assert np.array_equal(b["shifts"][u], q_only)
    whole = (
        T.run_span(b["span"], b["schedule"], limits=LIMITS, costs=c1, u=53)["ret"]
        .loc[b["S"].index]
        .to_numpy()
    )
    assert np.array_equal(b["whole_shifts"][53], whole) and not np.array_equal(whole, b["shifts"][53])
    for target, name, wrap, message in (
        (T, "run_span", _stressed_run_span(T.run_span), "S's R_0 does not hold S's book"),
        (T, "run_span", _nudged(T.run_span), "R_0 is not S on the first fold's kept rows"),
        (D, "run_q_shift", _stressed_q_shift(D.run_q_shift), "S's q-only shift u = 53 does not hold"),
        (
            T,
            "run_span",
            _stressed_run_span(T.run_span, lambda kw: kw.get("u", 0) > 0),
            "S's whole-schedule shift u = 53 does not hold",
        ),
    ):
        with monkeypatch.context() as mp:
            mp.setattr(target, name, wrap)
            with pytest.raises(S.Stop, match=message):
                bundle(walk)
    original_n0, original_x, original_bt = T.always_in_n0, T.exposure_x, D.downvol_backtest
    with monkeypatch.context() as mp:
        mp.setattr(T, "always_in_n0", lambda *a, costs, **k: original_n0(*a, costs=costs.stressed(), **k))
        with pytest.raises(S.Stop, match="stop rule 14: S's N0 fold 0"):
            bundle(walk)
    with monkeypatch.context() as mp:
        mp.setattr(T, "exposure_x", lambda *a, costs, **k: original_x(*a, costs=costs.stressed(), **k))
        with pytest.raises(S.Stop, match="stop rule 14: S's X fold 0"):
            bundle(walk)

    def other_orders(params, bars, *, limits, costs, **kw):
        res = original_bt(params, bars, limits=limits, costs=costs, **kw)
        if costs.pool_fee_bps > Costs.from_yaml().pool_fee_bps:
            res.attrs["order_hash"] = "another"
        return res

    with monkeypatch.context() as mp:
        mp.setattr(D, "downvol_backtest", other_orders)
        with pytest.raises(S.Stop, match="stop rule 13: S fold 0: the orders at 2x differ"):
            bundle(walk)
    # a fixed run's own N0 holds its book at every fold's t0
    run = D.downvol_backtest(params[2], panel, limits=LIMITS, costs=Costs.from_yaml())
    n0 = S.fixed_n0(panel, run, windows, 0.5, limits=LIMITS, costs=Costs.from_yaml())
    assert n0.index.equals(b["S"].index)
    with monkeypatch.context() as mp:
        mp.setattr(T, "always_in_n0", lambda *a, costs, **k: original_n0(*a, costs=costs.stressed(), **k))
        with pytest.raises(S.Stop, match="a fixed run's N0 fold 0"):
            S.fixed_n0(panel, run, windows, 0.5, limits=LIMITS, costs=Costs.from_yaml())


def _wf_perturbed(original, key):
    def walk_forward_optimize(*args, **kwargs):
        out = original(*args, **kwargs)
        if key == "oos_returns":
            out["oos_returns"] = out["oos_returns"].copy()
            out["oos_returns"].iloc[10] += 1e-12
        else:
            out["folds"].loc[2, "oos_trades"] += 1
        return out

    return walk_forward_optimize


def _bad_n0_target(original):
    def always_in_n0(bars, base, t0, share, **kw):
        return T.from_t0(bars, base, t0, (0.7, 0.2), limits=kw["limits"], costs=kw["costs"])

    return always_in_n0


@pytest.mark.parametrize(
    "module, target, wrap, message",
    [
        ("RT", "walk_forward_optimize", partial(_wf_perturbed, key="oos_returns"), "H0 does not reproduce"),
        ("RT", "walk_forward_optimize", partial(_wf_perturbed, key="trades"), "fold 2: kept fills differ"),
        ("T", "always_in_n0", _bad_n0_target, "stopped: stop rule 12"),
        ("T", "g6_statistic", lambda f: lambda r: f(r) + 1e-12, "G6's statistic is not overfitting_report's"),
    ],
)
def test_the_run_s_own_checks_stop_it(
    tmp_path, clean_git, monkeypatch, fast_timing, module, target, wrap, message
):
    mod = {"RT": RT, "T": T}[module]
    monkeypatch.setattr(mod, target, wrap(getattr(mod, target)))
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    status = summary(out)["status"]
    assert message in status, status


def test_the_counted_runs_and_the_measurement_points_are_checked():
    evals = pd.DataFrame({"counted": [True] * 48 + [False] * 5})
    assert RT.check_counted(evals) == 48
    for n in (47, 49, 78):
        with pytest.raises(S.Stop, match=f"{n} counted runs logged; the strict count needs 48"):
            RT.check_counted(pd.DataFrame({"counted": [True] * n}))
    pts = dict.fromkeys(V.measurement_points(), True)
    assert (
        list(RT.check_points(dict(reversed(list(pts.items()))))) == V.measurement_points()
    )  # the table's order
    with pytest.raises(S.Stop, match="measurement points differ"):
        RT.check_points(dict.fromkeys(T.measurement_points(), True))  # trend-steady's G5 names (buffer)
    with pytest.raises(S.Stop, match="measurement points differ"):
        RT.check_points({**pts, ("G7", "theta_final(A)"): True})  # not a point in Branch R (M13)
    with pytest.raises(S.Stop, match="measurement points differ"):
        RT.check_points({k: v for k, v in pts.items() if k != ("R1", "default")})


def test_the_gate_summary_and_the_narrowing_line_by_hand():
    pts = dict.fromkeys(V.measurement_points(), True)
    assert RT.gate_summary(pts) == {
        **dict.fromkeys(
            ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8-excess", "R1", "S(s_k) check"], "PASS"
        ),
        "G9": "NOT RUN",
    }
    one = {**pts, ("G6", "grid s=0.60"): False, ("G2", "S(0.30) at 2x"): None}
    g = RT.gate_summary(one)
    assert g["G6"] == "FAIL" and g["G2"] == "MISSING" and g["G1"] == "PASS"
    # a failing point decides over a MISSING one
    both = {**pts, ("G7", "grid s=0.30"): None, ("G7", "S"): False}
    assert RT.gate_summary(both)["G7"] == "FAIL"
    ctx = {"budget": 0.35}
    grid = {s: {"p5": -0.20 - s / 10} for s in T.ALLOWED_S}
    sk = {s: {"p5": -0.25 - s / 10} for s in T.ALLOWED_S}  # deepest at 0.60: -0.31
    assert RT.narrowing_line(ctx, pts, grid, sk, 0.4)["status"] == "not needed"
    risk = {**pts, ("G6", "grid s=0.60"): False}
    got = RT.narrowing_line(ctx, risk, grid, sk, 0.4)
    assert got["status"] == "keeps" and got["kept"] == [0.3, 0.4, 0.5] and got["dropped"] == [0.6]
    assert got["margins"] == [(0.5, -0.30 + 0.35)]  # the new edge's deepest p5 (S(0.50): -0.25 - 0.05)
    assert RT.narrowing_line(ctx, {**risk, ("G7", "grid s=0.30"): False}, grid, sk, 0.4)["status"] == "fails"
    assert (
        RT.narrowing_line(ctx, {**risk, ("G1", "S"): False}, grid, sk, 0.4)["status"] == "fails"
    )  # a non-risk point at S
    assert (
        RT.narrowing_line(ctx, {**risk, ("G5", "(b) default target_vol x1.2"): False}, grid, sk, 0.4)[
            "status"
        ]
        == "fails"
    )
    assert RT.narrowing_line(ctx, {**risk, ("G6", "S"): False}, grid, sk, 0.4)["line"].startswith(
        "narrowing fails: G6 fails at S"
    )
    assert RT.narrowing_line(ctx, risk, grid, sk, 0.6)["line"] == "narrowing fails: it would drop the default"


def test_share_changes_risk_and_trade_frequency_by_hand():
    """R3's q days (INTERPRETATIONS["r3"]), the fold description's share changes and the order-log helpers on a
    hand-built path: a flat market whose one fall makes the downside deviation large for L days, so q steps down and
    back up (a jump UP would move nothing: up days do not count)."""
    idx = T.train_grid()[:120]
    c = np.full(len(idx), 100.0)
    c[40:] = 50.0  # one halving on row 40: the 10-row window holds it on rows 40..49
    up = np.where(np.arange(len(idx)) >= 40, 200.0, 100.0)  # the same path with a doubling instead
    up_panel = make_panel(
        {
            a: pd.DataFrame(
                {"open": up, "high": up * 1.01, "low": up * 0.99, "close": up, "volume": 1.0}, index=idx
            )
            for a in ("BTC", "ETH")
        },
        snapshot_id="hand",
    )
    up_q = D.downvol_path(up_panel, 10, 0.6, 0.5).q
    assert (up_q[14:] == 1.0).all()  # never steps back on a rise
    assert (V.vol_path(up_panel, 10, 0.6, 0.5).q[42:56] == 0.0).all()  # vol-steady's sigma does
    bars = {
        a: pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1.0}, index=idx)
        for a in ("BTC", "ETH")
    }
    panel = make_panel(bars, snapshot_id="hand")
    res = D.downvol_backtest(
        {"lookback": 10, "target_vol": 0.6, "crypto_share": 0.5}, panel, limits=LIMITS, costs=Costs()
    )
    q = res.attrs["q"]
    assert res.attrs["activation"] == 14 and (q[14:42] == 1.0).all()  # sigma_down = 0 before the fall: m = 1
    # Mondays 42 and 49 hold the jump in their 10-row windows (rows 33-42 and 40-49); Monday 56 no longer does
    assert (q[42:56] == 0.0).all() and (q[56:] == 1.0).all()
    assert (
        RT.share_changes(res.attrs["share"], 30, 119) == 2
        and RT.share_changes(res.attrs["share"], 0, 119) == 3
    )
    assert RT.share_changes(res.attrs["share"], 30, 56) == 1  # a change on the last close fills after it
    assert RT.counted_changes(res.attrs["share"], 0, 119) == [42, 56]  # the first buy (row 14) is not counted
    assert RT.counted_changes(res.attrs["share"], 0, 56) == [42]
    kept = idx[30:]
    log = S.fixed_log(res, kept)
    assert list(log["reason"]) == ["re-cut", "re-cut"] and list(log["filled"]) == [idx[43], idx[57]]
    rows = S.plain(res.loc[kept])
    risk = S.r2_r5(LIMITS, rows, log, q[30:])
    assert risk["R3"]["days_at_q"] == {"0": 14 / 90, "0.25": 0.0, "0.5": 0.0, "0.75": 0.0, "1": 76 / 90}
    assert risk["R3"]["days_with_crypto"] == 76 / 90 == float(np.mean((rows["w_BTC"] + rows["w_ETH"]) > 0))
    assert risk["R2"]["limit_fixes"] == 0 and risk["R5"]["longest_all_usdc_rows"] == 14
    assert RT.kept_q([res], [type("W", (), {"t0": idx[29], "last": idx[-1]})()]).tolist() == q[30:].tolist()
    with pytest.raises(ValueError, match="one q per kept row"):
        S.r2_r5(LIMITS, rows, log, q[31:])
    freq = S.frequency(log, kept, [type("W", (), {"t0": idx[29], "last": idx[-1]})()])
    assert freq["overall"]["fills"]["worst"] == 2.0 and freq["fold 0"] == freq["overall"]  # 14 days apart
    assert freq["overall"]["legs"]["worst"] == 4.0 and freq["overall"]["switches"]["worst"] == 4.0


# -------------------------------------------------------------------------------- run 0, as recorded


def test_run_0_names_its_studies_and_counts_every_trial_and_run(train0):
    out = train0["out"]
    s = summary(out)
    r = s["results"]
    n = s["start"]["settings"]["n_trials"]
    names = [
        f"downvol-steady-s{seed}_{part}"
        for seed in (0, 1)
        for part in ("final", "wf00", "wf01", "wf02", "wf03", "wf04")
    ]
    assert S.study_dirs(out / "train") == names
    assert s["status"] == "complete" and r["trials"]["n_raw"] == 12 * n
    assert (
        r["trials"]["n_strict"] == 12 * n + 49 + 2400 and r["trials"]["n_strict_k4_15"] == 12 * n + 63 + 2400
    )
    assert r["trials"]["prior_trials"] == 2400
    trials = pd.read_parquet(out / "train" / "run0" / "trials.parquet")
    assert len(trials) == 12 * n and set(trials["run"]) == {0} and set(trials["seed"]) == {0, 1}
    ctx = json.loads(trials["context"].iloc[0])
    assert (
        ctx["config_hash"] == s["start"]["config_hash"]
        and ctx["branch"] == "R"
        and ctx["max_drawdown_budget_pct"] == 35
    )
    assert ctx["risk_levels_sha256"] == s["start"]["risk_limits"]["sha256"] and ctx["run"] == 0
    csv = pd.read_csv(out / "tracked" / "trials.csv")
    assert len(csv) == len(trials) and list(csv.columns) == list(trials.columns)
    ev = pd.read_parquet(out / "train" / "run0" / "evaluations.parquet")
    assert int(ev["counted"].sum()) == r["trials"]["counted_runs"] == 48 and len(
        pd.read_csv(out / "tracked" / "evaluations.csv")
    ) == len(ev)
    counted = ev[ev["counted"]].groupby(["kind", "source"]).size().to_dict()
    assert counted == {
        ("plateau", "KRAKEN"): 12,
        ("plateau_default", "KRAKEN"): 6,
        ("S_2x", "KRAKEN"): 2,
        ("S", "BINANCE"): 1,
        ("check_day", "KRAKEN"): 7,
        ("grid", "KRAKEN"): 4,
        ("grid_2x", "KRAKEN"): 4,
        ("S_sk", "KRAKEN"): 4,
        ("S_sk_2x", "KRAKEN"): 4,
        ("R4", "KRAKEN"): 4,
    }
    shifts = ev[ev["kind"] == "shift"]
    assert len(shifts) == 2 * 207 + 155 and set(shifts.loc[shifts["source"] == "KRAKEN", "offset"]) == set(
        range(53, 260)
    )
    assert (ev["kind"] == "lead").sum() == 2 * 52 and (ev["kind"] == "shift_sk").sum() == 4 * 207
    whole = ev[ev["kind"] == "shift_whole"]  # E1-whole: a description, never counted
    assert (
        len(whole) == 2 * 207 and not whole["counted"].any() and set(whole["offset"]) == set(range(53, 260))
    )
    assert not ev["kind"].str.contains("phi|placebo|fresh").any()  # no stop-loss variant (section 11A)
    # the executor runs tallied equal the projection's table (stop rule 17); the bootstraps fit inside it
    units = S.run_counts()
    assert r["tally"]["rule"] + r["tally"]["comparator"] == units["run"] and set(r["tally"]) == {
        "rule",
        "comparator",
        "bootstrap",
    }
    assert r["tally"]["bootstrap"] == S.RUN_PARTS["bootstrap"][next(iter(S.RUN_PARTS["bootstrap"]))]
    assert [json.loads(x)["run"] for x in (out / "RUNLOG.jsonl").read_text().splitlines()] == [0]
    assert r["triage_required"] is False and r["failed_trials"] == []


def test_dry_runs_never_write_into_the_repo(train0):
    assert here_hashes() == train0["before"]
    assert (train0["out"] / "RUNLOG.jsonl").is_file() and (train0["out"] / "tracked" / "trials.csv").is_file()


def test_run_0_s_verdict_headline_and_gates_follow_the_rules(train0):
    r = summary(train0["out"])["results"]
    points = {(p["item"], p["point"]): p["value"] for p in r["points"]}
    assert list(points) == V.measurement_points()
    assert r["verdict"] == V.verdict(r["criteria"], changes=r["seeds"]["A"]["P"]["total"])
    assert r["headline"] == S.jsonable(V.headline(r["verdict"], points))
    assert r["gates"] == RT.gate_summary(points)
    assert "stop" not in r
    assert r["own"] == {
        "verdict": r["verdict"]["label"],
        "headline": r["headline"]["headline"],
        "look_earned": r["verdict"]["look_earned"],
        "e1_rank_p": r["seeds"]["A"]["e1"]["rank_p"],
        "e2_p": r["seeds"]["A"]["e2"]["p"],
    }
    assert r["reported"]["verdict"] == r["verdict"]["label"] and len(r["reported"]["runs"]) == 1
    assert r["pending"] == RT.pending(r["reported"]) and (r["pending"] is None) == (
        not r["reported"]["look_earned"]
    )
    assert RT.pending({"look_earned": True}) == "E9 at the single validate look"
    assert RT.pending({"look_earned": False}) is None and RT.pending({"look_earned": None}) is None
    # run 0 is reported beside no earlier run (stop rule 18): its reported record is its own
    assert r["reported"] == {
        **{k: r["own"][k] for k in ("verdict", "headline", "look_earned")},
        "superseded": None,
        "trigger": None,
        "beside": [],
        "runs": [{"run": 0, "e1_rank_p": r["own"]["e1_rank_p"], "e2_p": r["own"]["e2_p"]}],
    }
    assert r["default"]["share"] == T.default_share(r["theta_final"]["A"]["params"]["crypto_share"])


# ------------------------------------------------------- every reported number recomputed (the #47 standard)


def _h0(panel, windows, params, limits, costs, like=None, weekday=0):
    return [
        D.downvol_backtest(
            dict(p), T.h0_slice(panel, w, like=like), limits=limits, costs=costs, weekday=weekday
        )
        for p, w in zip(params, windows, strict=True)
    ]


def _stitch(runs, windows):
    return pd.concat([sd.kept_returns(r, w.t0) for r, w in zip(runs, windows, strict=True)])


def _sh(r):
    return stats.annualized_sharpe(np.asarray(r, dtype=float), 365)


def _n0(panel, runs, windows, params, limits, costs):
    return _stitch(
        [
            T.always_in_n0(
                T.h0_slice(panel, w),
                r.attrs["targets"],
                w.t0,
                p["crypto_share"],
                limits=limits,
                costs=costs,
                base_states=r.attrs["z"],
            )
            for r, w, p in zip(runs, windows, params, strict=True)
        ],
        windows,
    )


def _span(panel, runs, windows, limits, costs, offsets, kept, shares, *, whole=False):
    """R_0 and its shifts rebuilt from the fold runs' share and q paths (volsteady.stitched_schedule,
    trend.run_span). The q-only shift of amendment M1 is written out here, not taken from lab.runner.downvol: at check
    c_k the share is s_fold(c_k) x q(c_((k + u) mod W)), z moving with q. With ``whole=True`` the shifts are VP's
    whole-schedule shifts (trend.shifted), E1-whole's."""
    span = panel.loc[: windows[-1].last]
    sched = V.stitched_schedule(
        span.index, windows, [r.attrs["z"] for r in runs], [r.attrs["share"] for r in runs]
    )
    w = len(sched.checks)
    q = np.array(
        [runs[i].attrs["q"][c] for c, i in zip(sched.checks.tolist(), sched.fold.tolist(), strict=True)]
    )
    s = np.array([float(shares[i]) for i in sched.fold.tolist()])
    assert np.array_equal(sched.share, s * q)

    def shifted(u):
        if whole:
            return T.shifted(sched, u)
        order = (np.arange(w) + u) % w
        return sched._replace(z=sched.z[order], share=s * q[order])

    r0 = T.run_span(span, sched, limits=limits, costs=costs)["ret"].loc[kept].to_numpy()
    shifts = {
        u: T.run_span(span, shifted(u), limits=limits, costs=costs)["ret"].loc[kept].to_numpy()
        for u in offsets
    }
    return r0, shifts, w


@pytest.fixture(scope="module")
def rebuilt(train0, tmp_path_factory):
    """The inputs of run 0, rebuilt from the synthetic bars and the logged choices with lab.runner.downvol,
    lab.runner.volsteady and lab.runner.trend only."""
    out, cfg = train0["out"], train0["cfg"]
    s = summary(out)
    limits = sd.steady_limits(cfg)
    c1 = Costs.from_yaml(cfg / "costs.yaml")
    c2 = c1.stressed()
    tmp = tmp_path_factory.mktemp("rebuilt")
    load = partial(S.load_study_panel, catalog_dir=tmp, config_dir=cfg, loader=S.synthetic_bar_loader(SEED))
    K, Bn = load(S.SOURCE, S.TRAIN_LAST_CLOSE), load(S.ROBUSTNESS, S.TRAIN_LAST_CLOSE)
    windows = T.fold_windows(K.index)
    return {
        "s": s,
        "r": s["results"],
        "limits": limits,
        "c1": c1,
        "c2": c2,
        "K": K,
        "Bn": Bn,
        "windows": windows,
        "train": out / "train",
        "resamples": s["start"]["settings"]["bootstrap_resamples"],
    }


def _seed(rb, label):
    r, K, windows, limits, c1, c2 = rb["r"], rb["K"], rb["windows"], rb["limits"], rb["c1"], rb["c2"]
    params = r["seeds"][label]["params"]
    runs, runs2 = _h0(K, windows, params, limits, c1), _h0(K, windows, params, limits, c2)
    s, s2 = _stitch(runs, windows), _stitch(runs2, windows)
    shares = [p["crypto_share"] for p in params]
    r0, shifts, w = _span(K, runs, windows, limits, c1, range(1, 260), s.index, shares)
    _, whole, _ = _span(K, runs, windows, limits, c1, range(53, 260), s.index, shares, whole=True)
    n0, n02 = _n0(K, runs, windows, params, limits, c1), _n0(K, runs2, windows, params, limits, c2)
    x = _stitch(
        [
            T.exposure_x(T.h0_slice(K, wd), rr, wd.t0, limits=limits, costs=c1)[0]
            for rr, wd in zip(runs, windows, strict=True)
        ],
        windows,
    )
    return {
        "params": params,
        "runs": runs,
        "S": s,
        "S2": s2,
        "R0": r0,
        "shifts": shifts,
        "whole": whole,
        "W": w,
        "N0": n0,
        "N0_2": n02,
        "X": x,
    }


def test_s_r0_and_the_luck_controls_are_recomputed_from_their_inputs(rebuilt):
    rb = rebuilt
    r, K, windows = rb["r"], rb["K"], rb["windows"]
    oos = pd.read_parquet(rb["train"] / "run0" / "oos.parquet")
    btc = K[("BTC", "close")]
    items = {}
    for label in ("A", "B"):
        x = _seed(rb, label)
        rec = r["seeds"][label]
        for name in ("S", "S2", "N0", "N0_2", "X"):
            np.testing.assert_array_equal(x[name].to_numpy(), oos[f"{name}_{label}"].to_numpy())
        np.testing.assert_array_equal(x["R0"], oos[f"R0_{label}"].to_numpy())
        np.testing.assert_array_equal(x["R0"][:364], x["S"].to_numpy()[:364])  # R_0 = S on fold 0's kept rows
        e1 = T.e1_test(x["R0"], x["shifts"], 260)
        assert rec["e1"] == S.jsonable({k: e1[k] for k in rec["e1"]}) and rec["e1"]["n_shifts"] == 207
        # E1-whole (a description) from VP's whole-schedule shifts; the two nulls differ where the folds' s differ
        e1w = T.e1_test(x["R0"], x["whole"], 260)
        assert rec["e1_whole"] == S.jsonable({k: e1w[k] for k in rec["e1_whole"]})
        assert (
            len({p["crypto_share"] for p in x["params"]}) > 1 and rec["e1"]["p50"] != rec["e1_whole"]["p50"]
        )
        np.testing.assert_array_equal(  # oos.parquet's percentile columns of both nulls
            np.percentile(np.vstack([x["shifts"][u] for u in range(53, 260)]), 50, axis=0),
            oos[f"shifts_{label}_p50"].to_numpy(),
        )
        np.testing.assert_array_equal(
            np.percentile(np.vstack([x["whole"][u] for u in range(53, 260)]), 50, axis=0),
            oos[f"shifts_whole_{label}_p50"].to_numpy(),
        )
        e2 = T.e2_test(x["S"], x["N0"], n_resamples=rb["resamples"])
        assert (rec["e2"]["d"], rec["e2"]["p"], rec["e2"]["holds"]) == (e2["d"], e2["p"], e2["holds"])
        e3 = [
            mc.max_drawdown(x["S"].to_numpy()),
            T.g6_statistic(x["S"].to_numpy()),
            mc.max_drawdown(x["X"].to_numpy()),
            T.g6_statistic(x["X"].to_numpy()),
        ]
        assert rec["e3"]["S"] == e3[:2] and rec["e3"]["X"] == e3[2:] and rec["items"]["E3"] == T.e3_holds(*e3)
        assert rec["e4"] == {"S_2x": _sh(x["S2"]), "N0_2x": _sh(x["N0_2"])} and rec["items"]["E4"] == (
            _sh(x["S2"]) > _sh(x["N0_2"])
        )
        assert rec["e6"] == S.jsonable(T.loyo(x["S"], x["N0"]))
        years = T.boom_years(btc, x["S"].index)
        assert rec["boom_years"] == years
        removals = []
        for removal, drop in zip(rec["e7"], (years[:1], years[:2]), strict=True):
            mask = T.without_years(x["S"].index, drop)
            row = {
                "E1": T.e1_test(x["R0"], x["shifts"], 260, keep=mask)["holds"],
                "E2": T.e2_test(x["S"][mask], x["N0"][mask], n_resamples=rb["resamples"])["holds"],
                "E3": T.e3_holds(
                    mc.max_drawdown(x["S"][mask].to_numpy()),
                    T.g6_statistic(x["S"][mask].to_numpy()),
                    mc.max_drawdown(x["X"][mask].to_numpy()),
                    T.g6_statistic(x["X"][mask].to_numpy()),
                ),
                "E4": bool(_sh(x["S2"][mask]) > _sh(x["N0_2"][mask])),
            }
            assert removal["removed"] == drop and {k: removal[k] for k in row} == row
            # the numbers each outcome judged, rebuilt too, not only the outcomes (#58)
            sm, xm = x["S"][mask].to_numpy(), x["X"][mask].to_numpy()
            e1_m = T.e1_test(x["R0"], x["shifts"], 260, keep=mask)
            e2_m = T.e2_test(x["S"][mask], x["N0"][mask], n_resamples=rb["resamples"])
            assert removal["rows"] == int(mask.sum())
            assert (
                removal["e1"] == S.jsonable({k: e1_m[k] for k in removal["e1"]}) and len(removal["e1"]) == 9
            )
            assert (removal["e2"]["d"], removal["e2"]["p"], removal["e2"]["n_resamples"]) == (
                e2_m["d"],
                e2_m["p"],
                rb["resamples"],
            )
            assert removal["e3"] == [
                mc.max_drawdown(sm),
                T.g6_statistic(sm),
                mc.max_drawdown(xm),
                T.g6_statistic(xm),
            ]
            assert removal["e4"] == [_sh(x["S2"][mask]), _sh(x["N0_2"][mask])]
            removals.append(row)
        assert rec["items"]["E7"] == T.boom_holds(removals, T.E7_ITEMS)
        power = V.power_count([rr.attrs["share"] for rr in x["runs"]], windows, K.index)
        assert rec["P"] == S.jsonable(power) and rec["items"]["P"] == power["holds"]
        # G5(a): each step applied to every fold at once
        for step, logged in zip(V.plateau_steps(x["params"], rb["limits"]), rec["plateau"], strict=True):
            sh = _sh(_stitch(_h0(K, windows, step["params"], rb["limits"], rb["c1"]), windows))
            assert logged["sharpe"] == sh
        b1 = pd.concat([sd.kept_returns(sd.buy_and_hold_b1(K, w, rb["c1"]), w.t0) for w in windows])
        b2 = pd.concat([sd.kept_returns(sd.fifty_fifty_b2(K, w, rb["c1"]), w.t0) for w in windows])
        for key, drop in (
            ("full", []),
            ("without the best bar-year", years[:1]),
            ("without the two best bar-years", years[:2]),
        ):
            m = T.without_years(x["S"].index, drop)
            a, c, d = _sh(x["S"][m]), _sh(b1[m]), _sh(b2[m])
            assert rec["g7"][key] == {"sharpe": a, "B1": c, "B2": d, "holds": bool(a > c and a > d)}
        split = sd.regime_split(x["S"], sd.regime_table(btc, x["S"].index), benchmark=x["N0"])
        assert (
            rec["g8"]["excess_pass"] == T.g8_excess_pass(split) and rec["g8"]["literal_pass"] == split["pass"]
        )
        log = pd.concat(
            [T.order_log(rr, w.t0) for rr, w in zip(x["runs"], windows, strict=True)], ignore_index=True
        )
        assert rec["R1"] == S.jsonable(
            {
                **T.r1_check(log, x["S"].index, T.covered_days(K.index, x["S"].index)),
                "order_hash": [rr.attrs["order_hash"] for rr in x["runs"]],
            }
        )
        studies = S.study_dirs(rb["train"])
        n_raw = r["trials"]["n_raw"]
        wf_eff = rec["overfitting_report"]["wf_efficiency"]
        rep = overfitting_report(
            {"oos_returns": x["S"], "wf_efficiency": wf_eff, "studies": studies, "total_trials": n_raw},
            rb["train"],
        )
        assert (
            rec["overfitting_report"] == S.jsonable(rep)
            and rec["g6"]["p5"] == rep["mc_drawdown_worst5pct"] == e3[1]
        )
        act = T.active_report(
            studies,
            rb["train"],
            first_row=15,
            oos_returns=x["S"].to_numpy(),
            n_raw=n_raw,
            n_strict=n_raw + 49 + 2400,  # section 14: VP's strict count plus vol-steady run 0's 2,400 trials
        )
        assert (
            rec["active_report"]["dsr_effective"] == act["dsr_effective"]
            and rec["active_report"]["pbo_mean"] == act["pbo_mean"]
        )
        assert rec["active_report"]["dsr_strict"] == S.jsonable(act["dsr_strict"])
        assert rec["items"]["G3"] == T.g3_g4(rep, act)["G3"] and rec["items"]["G4"] == T.g3_g4(rep, act)["G4"]
        assert rec["items"]["G1"] == (rep["oos_sharpe_annual"] >= 1.0) and rec["items"]["G2"] == (
            _sh(x["S2"]) > 0.5
        )
        assert rec["items"]["G6"] == (e3[1] >= -0.35)
        items[label] = rec["items"]
        if label == "A":
            seed_a = x
            _check_q_only_descriptions(r["descriptions"], x)
    # E5, E8 and the verdict
    e5a = T.e5a_holds(items["A"], items["B"], r["seeds"]["A"]["sharpe"], r["seeds"]["B"]["sharpe"])
    assert r["e5"]["a"] == S.jsonable(e5a)
    sharpes = {}
    for day in (1, 2, 3, 4, 5, 6, None):
        sharpes["daily" if day is None else str(day)] = _sh(
            _stitch(_h0(K, windows, seed_a["params"], rb["limits"], rb["c1"], weekday=day), windows)
        )
    assert {k: v["sharpe"] for k, v in r["e5"]["b"]["weekdays"].items()} == sharpes
    assert r["e5"]["b"]["holds"] == T.keeps_share(_sh(seed_a["S"]), [sharpes[str(d)] for d in range(1, 7)])
    bw, bp = windows[1:], seed_a["params"][1:]
    bruns = _h0(rb["Bn"], bw, bp, rb["limits"], rb["c1"], like=K)
    bs = _stitch(bruns, bw)
    assert bs.index.equals(seed_a["S"].index[seed_a["S"].index > windows[1].t0])
    shares_b = [p["crypto_share"] for p in bp]
    br0, bshift, bw_n = _span(rb["Bn"], bruns, bw, rb["limits"], rb["c1"], range(53, 208), bs.index, shares_b)
    assert bw_n == 208
    be1 = T.e1_test(br0, bshift, 208)  # E8 on the 155 q-only shifts (M1)
    bn0 = _stitch(
        [
            T.always_in_n0(
                T.h0_slice(rb["Bn"], w, like=K),
                x.attrs["targets"],
                w.t0,
                p["crypto_share"],
                limits=rb["limits"],
                costs=rb["c1"],
                base_states=x.attrs["z"],
            )
            for x, w, p in zip(bruns, bw, bp, strict=True)
        ],
        bw,
    )
    be2 = T.e2_test(bs, bn0, n_resamples=rb["resamples"])
    assert (
        r["e8"]["e1"]["rank_p"] == be1["rank_p"]
        and r["e8"]["e1"]["n_shifts"] == 155
        and r["e8"]["e2"]["p"] == be2["p"]
    )
    criteria = {
        **{k: items["A"][k] for k in ("E1", "E2", "E3", "E4", "E6", "E7", "P")},
        "E5": bool(e5a["holds"] and r["e5"]["b"]["holds"]),
        "E8": bool(be1["holds"] and be2["holds"]),
    }
    assert r["criteria"] == criteria
    assert r["verdict"] == V.verdict(criteria, changes=r["seeds"]["A"]["P"]["total"])
    # the fold descriptions' share changes (first buys included) by hand
    for fold, (rr, w) in zip(
        r["descriptions"]["folds"][:5], zip(seed_a["runs"], windows, strict=True), strict=True
    ):
        s_ = rr.attrs["share"]
        p0, pl = rr.index.get_loc(w.t0), rr.index.get_loc(w.last)
        assert fold["share_changes"] == sum(
            1 for t in range(len(s_)) if p0 <= t <= pl - 1 and s_[t] != (s_[t - 1] if t else 0.0)
        )


def _check_q_only_descriptions(d, x):
    """M2: the q-only shift (written out in ``_span``, never taken from lab.runner.downvol) is also used for the
    descriptions B3-lead, the lag rank, the leave-one-year-out E1, the bear-year E1 and the stitched shifts'
    percentiles (seed A only). Each is recomputed here from the shifts u = 1..259; VP's whole-schedule shifts give
    other numbers on seed 7 (#73)."""
    kept, sh0, shifts = x["S"].index, _sh(x["R0"]), x["shifts"]
    years = sorted(set(T.bar_years(kept).tolist()))
    assert sorted(d["leave_one_year_out"]) == [str(y) for y in years]
    for year in years:
        e1 = T.e1_test(x["R0"], shifts, 260, keep=T.without_years(kept, [year]))
        row = d["leave_one_year_out"][str(year)]
        assert row["removed"] == [year] and (row["e1_rank_p"], row["E1"]) == (e1["rank_p"], e1["holds"])
    bears = T.without_years(kept, list(S.BEAR_YEARS))
    assert S.BEAR_YEARS == (2018, 2022)
    assert d["bear_years_removed"]["e1_rank_p"] == T.e1_test(x["R0"], shifts, 260, keep=bears)["rank_p"]
    st = d["stitched"]
    guarded = [_sh(shifts[u]) for u in range(53, 260)]
    assert st["shifts"] == S.jsonable(
        {**mc.percentiles(guarded), "rank_p": T.e1_test(x["R0"], shifts, 260)["rank_p"]}
    )
    lead = [_sh(shifts[u]) for u in range(1, 53)]
    assert st["b3_lead"] == S.jsonable(
        {**mc.percentiles(lead), "rank_p": (1 + sum(v >= sh0 for v in lead)) / 53}
    )
    lag = [_sh(shifts[u]) for u in range(208, 260)]
    assert st["r0_rank_among_lags"] == (1 + sum(v >= sh0 for v in lag)) / 53
    assert st["lags"] == S.jsonable(mc.percentiles(lag))


def test_the_range_s_points_are_recomputed_from_their_inputs(rebuilt):
    """theta_final(A), the default, the four grid steps and S(s_k), and every point of section 10's table."""
    rb = rebuilt
    r, K, windows, limits, c1, c2 = rb["r"], rb["K"], rb["windows"], rb["limits"], rb["c1"], rb["c2"]
    theta = r["theta_final"]["A"]
    logged = pd.read_parquet(
        rb["train"] / theta["study"] / "returns" / f"trial_{theta['trial_number']:06d}.parquet"
    ).iloc[:, 0]
    trun = D.downvol_backtest(theta["params"], K, limits=limits, costs=c1)
    np.testing.assert_array_equal(trun["ret"].to_numpy(), logged.to_numpy())
    trials = S.trial_table(rb["train"], [theta["study"]])
    assert S.plain_params(stable_region(trials, list(V.SPECS), k=10)["params"]) == theta["params"]
    seed_a = r["seeds"]["A"]
    params_a = seed_a["params"]
    kept = _stitch(_h0(K, windows, params_a, limits, c1), windows).index
    covered = T.covered_days(K.index, kept)
    btc = K[("BTC", "close")]
    years = T.boom_years(btc, kept)
    b1 = pd.concat([sd.kept_returns(sd.buy_and_hold_b1(K, w, c1), w.t0) for w in windows])
    b2 = pd.concat([sd.kept_returns(sd.fifty_fifty_b2(K, w, c1), w.t0) for w in windows])
    sh_s = seed_a["sharpe"]
    pts, nums = {}, {}
    default = T.default_share(theta["params"]["crypto_share"])
    assert r["default"]["share"] == default
    for s_k in T.ALLOWED_S:
        p = {**theta["params"], "crypto_share": s_k}
        run1, run2 = (
            D.downvol_backtest(p, K, limits=limits, costs=c1),
            D.downvol_backtest(p, K, limits=limits, costs=c2),
        )
        g = r["grid"][f"{s_k:.2f}"]
        series = run1["ret"].loc[kept]
        assert (g["sharpe"], g["sharpe_2x"], g["p5"]) == (
            _sh(series),
            _sh(run2["ret"].loc[kept]),
            T.g6_statistic(series.to_numpy()),
        )
        n0 = pd.concat(
            [
                sd.kept_returns(
                    T.always_in_n0(
                        T.h0_slice(K, w),
                        run1.attrs["targets"][: len(T.h0_slice(K, w))],
                        w.t0,
                        s_k,
                        limits=limits,
                        costs=c1,
                        base_states=run1.attrs["z"][: len(T.h0_slice(K, w))],
                    ),
                    w.t0,
                )
                for w in windows
            ]
        )
        split = sd.regime_split(series, sd.regime_table(btc, kept), benchmark=n0)
        log = T.order_log(run1)
        log = log[pd.DatetimeIndex(log["filled"]).isin(kept)]
        name = f"grid s={s_k:.2f}"
        pts[("G1", name)] = g["sharpe"] >= 1.0
        pts[("G2", f"{name} at 2x")] = g["sharpe_2x"] > 0.5
        pts[("G5", f"(c) {name}")] = T.keeps_share(sh_s, [g["sharpe"]])
        pts[("G6", name)] = g["p5"] >= -0.35
        pts[("G8-excess", name)] = T.g8_excess_pass(split)
        pts[("R1", name)] = T.r1_check(log, kept, covered)["holds"]
        nums[("G1", name)] = nums[("G5", f"(c) {name}")] = [_sh(series)]
        nums[("G2", f"{name} at 2x")] = [_sh(run2["ret"].loc[kept])]
        nums[("G6", name)] = [T.g6_statistic(series.to_numpy())]
        nums[("G8-excess", name)] = split
        nums[("R1", name)] = {**T.r1_check(log, kept, covered), "order_hash": [run1.attrs["order_hash"]]}
        for prefix in [name, "default"] if s_k == default else [name]:
            for suffix, drop in (
                ("", []),
                (" without the best bar-year", years[:1]),
                (" without the two best bar-years", years[:2]),
            ):
                m = T.without_years(kept, drop)
                a, c, d = _sh(series[m]), _sh(b1[m]), _sh(b2[m])
                pts[("G7", prefix + suffix)] = bool(a > c and a > d)
                nums[("G7", prefix + suffix)] = {"sharpe": a, "B1": c, "B2": d}
        if s_k == default:
            pts[("G8-excess", "default")] = pts[("G8-excess", name)]
            pts[("R1", "default")] = pts[("R1", name)]
            nums[("G8-excess", "default")], nums[("R1", "default")] = split, nums[("R1", name)]
        # S(s_k): the walk-forward with each fold's s replaced, its R_0(s_k) and 207 shifts, its N0(s_k)
        pk = [{**q, "crypto_share": s_k} for q in params_a]
        runs, runs2 = _h0(K, windows, pk, limits, c1), _h0(K, windows, pk, limits, c2)
        sk_s = _stitch(runs, windows)
        r0, shifts, _ = _span(K, runs, windows, limits, c1, range(53, 260), kept, [s_k] * 5)
        _, whole_k, _ = _span(K, runs, windows, limits, c1, (53, 259), kept, [s_k] * 5, whole=True)
        for u in (53, 259):  # one s: the q-only shifts are VP's whole-schedule shifts bit for bit (M1)
            np.testing.assert_array_equal(shifts[u], whole_k[u])
        e1, e2 = (
            T.e1_test(r0, shifts, 260),
            T.e2_test(sk_s, _n0(K, runs, windows, pk, limits, c1), n_resamples=rb["resamples"]),
        )
        k = r["s_k"][f"{s_k:.2f}"]
        assert (k["sharpe"], k["sharpe_2x"], k["p5"]) == (
            _sh(sk_s),
            _sh(_stitch(runs2, windows)),
            T.g6_statistic(sk_s.to_numpy()),
        )
        assert (k["e1"]["rank_p"], k["e1"]["holds"], k["e2"]["p"], k["e2"]["holds"]) == (
            e1["rank_p"],
            e1["holds"],
            e2["p"],
            e2["holds"],
        )
        kn = f"S({s_k:.2f})"
        pts[("G1", kn)] = k["sharpe"] >= 1.0
        pts[("G2", f"{kn} at 2x")] = k["sharpe_2x"] > 0.5
        pts[("G6", kn)] = k["p5"] >= -0.35
        pts[("S(s_k) check", f"E1 at {kn}")] = e1["holds"]
        pts[("S(s_k) check", f"E2 at {kn}")] = e2["holds"]
        nums[("G1", kn)], nums[("G2", f"{kn} at 2x")] = [_sh(sk_s)], [_sh(_stitch(runs2, windows))]
        nums[("G6", kn)] = [T.g6_statistic(sk_s.to_numpy())]
        nums[("S(s_k) check", f"E1 at {kn}")] = [e1["rank_p"]]
        nums[("S(s_k) check", f"E2 at {kn}")] = [e2["d"], e2["p"]]
    for step, logged in zip(
        V.plateau_steps([{**theta["params"], "crypto_share": default}], limits),
        r["default"]["g5b"],
        strict=True,
    ):
        sh = _sh(D.downvol_backtest(step["params"][0], K, limits=limits, costs=c1)["ret"].loc[kept])
        assert logged["sharpe"] == sh
        pts[("G5", f"(b) default {logged['step']}")] = T.keeps_share(sh_s, [sh])
        nums[("G5", f"(b) default {logged['step']}")] = [sh]
    # the points measured at S, from S, S at 2x, its own N0 and its G5(a) steps, rebuilt here
    runs_a, runs_a2 = _h0(K, windows, params_a, limits, c1), _h0(K, windows, params_a, limits, c2)
    s_a = _stitch(runs_a, windows)
    for step in V.plateau_steps(params_a, limits):
        sh = _sh(_stitch(_h0(K, windows, step["params"], limits, c1), windows))
        name = f"(a) {step['param']} x{step['factor']:g}"
        pts[("G5", name)], nums[("G5", name)] = T.keeps_share(_sh(s_a), [sh]), [sh]
    for suffix, drop in (
        ("", []),
        (" without the best bar-year", years[:1]),
        (" without the two best bar-years", years[:2]),
    ):
        m = T.without_years(kept, drop)
        a, c, d = _sh(s_a[m]), _sh(b1[m]), _sh(b2[m])
        pts[("G7", "S" + suffix)], nums[("G7", "S" + suffix)] = (
            bool(a > c and a > d),
            {"sharpe": a, "B1": c, "B2": d},
        )
    rep, act = seed_a["overfitting_report"], seed_a["active_report"]  # rebuilt in the seed test
    split_s = sd.regime_split(
        s_a, sd.regime_table(btc, kept), benchmark=_n0(K, runs_a, windows, params_a, limits, c1)
    )
    log_s = pd.concat([T.order_log(x, w.t0) for x, w in zip(runs_a, windows, strict=True)], ignore_index=True)
    r1_s = {**T.r1_check(log_s, kept, covered), "order_hash": [x.attrs["order_hash"] for x in runs_a]}
    log = T.order_log(trun)
    r1_t = {
        **T.r1_check(log[pd.DatetimeIndex(log["filled"]).isin(kept)], kept, covered),
        "order_hash": [trun.attrs["order_hash"]],
    }
    for key, value, number in (
        (("G1", "S"), _sh(s_a) >= 1.0, [_sh(s_a)]),
        (("G2", "S at 2x"), _sh(_stitch(runs_a2, windows)) > 0.5, [_sh(_stitch(runs_a2, windows))]),
        (("G3", "S (all rows)"), rep["dsr_effective_count"] >= 0.95, [rep["dsr_effective_count"]]),
        (("G3", "S (active rows)"), act["dsr_effective"] >= 0.95, [act["dsr_effective"]]),
        (("G4", "search studies (all rows)"), rep["pbo_mean"] <= 0.25, [rep["pbo_mean"]]),
        (("G4", "search studies (active rows)"), act["pbo_mean"] <= 0.25, [act["pbo_mean"]]),
        (("G6", "S"), T.g6_statistic(s_a.to_numpy()) >= -0.35, [T.g6_statistic(s_a.to_numpy())]),
        (("G8-excess", "S"), T.g8_excess_pass(split_s), split_s),
        (("R1", "S"), r1_s["holds"], r1_s),
        (("R1", "theta_final(A)"), r1_t["holds"], r1_t),
    ):
        pts[key], nums[key] = value, number
    recorded = {(p["item"], p["point"]): p["value"] for p in r["points"]}
    assert set(pts) == set(recorded) and {k: bool(v) for k, v in pts.items()} == recorded
    recorded_nums = {(p["item"], p["point"]): p["numbers"] for p in r["points"]}
    for (
        key
    ) in recorded:  # the numbers each point judged, rebuilt from their inputs (a wiring break moves them)
        assert recorded_nums[key] == S.jsonable(nums[key]), key
    assert r["headline"] == S.jsonable(V.headline(r["verdict"], recorded))
    for (
        s_k
    ) in T.ALLOWED_S:  # the range table (section 16): both drawdowns and margins for every allowed value
        rng = r["descriptions"]["ranges"][f"{s_k:.2f}"]
        assert (
            rng["grid"]["margin"] == r["grid"][f"{s_k:.2f}"]["p5"] + 0.35
            and rng["S(s_k)"]["p5"] == r["s_k"][f"{s_k:.2f}"]["p5"]
        )


def test_the_dsr_counts_and_the_descriptions_are_recomputed(rebuilt):
    rb = rebuilt
    r = rb["r"]
    studies = S.study_dirs(rb["train"])
    trial_sharpes = sd.report_trial_sharpes(studies, rb["train"])
    s = pd.read_parquet(rb["train"] / "run0" / "oos.parquet")["S_A"].to_numpy()
    d = r["descriptions"]["dsr"]
    n_raw = r["trials"]["n_raw"]
    # section 14: VP's strict count plus vol-steady run 0's 2,400 trials
    assert d["n_strict"] == r["trials"]["n_strict"] == n_raw + 49 + 2400
    assert d["strict"] == stats.deflated_sharpe_ratio(s, trial_sharpes, n_trials=n_raw + 2449)["dsr"]
    assert d["strict_k4_15"] == stats.deflated_sharpe_ratio(s, trial_sharpes, n_trials=n_raw + 2463)["dsr"]
    assert (
        d["n_raw"] == n_raw and d["effective"] == r["seeds"]["A"]["overfitting_report"]["dsr_effective_count"]
    )
    assert r["trials"]["minus_10_trials"] == {
        st: int((S.trial_table(rb["train"], [st])["value"] == -10.0).sum()) for st in studies
    }
    mcd = r["descriptions"]["monte_carlo"]
    assert mcd["block_60"] == S.jsonable(
        mc.percentiles(mc.block_bootstrap_drawdowns(s, mean_block=60, n_sims=1000, seed=0), (5, 50))
    )
    assert (
        r["descriptions"]["trades_per_parameter"]["per_2"]
        == r["descriptions"]["trades_per_parameter"]["kept_fills"] / 2
    )
    pbo = r["pbo_per_study"]
    for st in studies:
        res = sd.study_pbo(st, rb["train"])
        assert (pbo[st] is None) == (res is None) and (res is None or pbo[st]["pbo"] == res["pbo"])
    # R4: the book sizes order as theta_final(A) does; customer fees and gas a year by hand at USD 500
    theta = r["theta_final"]["A"]["params"]
    kept = pd.read_parquet(rb["train"] / "run0" / "oos.parquet").index
    costs = Costs.from_yaml(rb["s"]["start"]["config_dir"] + "/costs.yaml", capital_usd=500.0)
    res = D.downvol_backtest(theta, rb["K"], limits=rb["limits"], costs=costs)
    legs = res.attrs["fills"][res.attrs["fills"]["ts"].isin(kept)]
    years = T.covered_days(rb["K"].index, kept) / 365.0
    fee = sum(
        float(res["cost"].iloc[int(t)])
        * (float(g["cost"].sum()) - costs.gas_usd_per_trade * len(g))
        / float(g["cost"].sum())
        for t, g in legs.groupby("bar")
    )
    r4 = r["descriptions"]["risk"]["R4"]["500"]
    assert r4["customer_fees_pct_a_year"] == pytest.approx(100 * fee / years, rel=1e-12)
    assert r4["gas_usd_a_year"] == costs.gas_usd_per_trade * len(legs) / years and r4[
        "sharpe_with_gas"
    ] == _sh(res["ret"].loc[kept])


# ------------------------------------------------------------ an amendment run, failed trials, stop rule 18


def _fails_in_fold_0(original, params, bars, **kwargs):
    if len(bars) == 365 and params["crypto_share"] > 0.5:  # only fold 0's training slice has 365 rows
        raise ValueError("an injected failure")
    return original(params, bars, **kwargs)


def _forced_edge(criteria, **kwargs):
    """Run 1's own verdict forced to EDGE, the look earned (a stand-in: the synthetic data give NO EDGE), so that only
    run 0's NO EDGE can hold the reported look back (stop rule 18, #58)."""
    return {"verdict": T.EDGE, "label": T.EDGE, "look_earned": True}


@pytest.fixture(scope="module")
def amended(train0, tmp_path_factory):
    """Amendment run 1 (trigger "other, after the verdict") on a copy of run 0, with fold-0 trials failing and its
    own verdict forced to EDGE (run 0's synthetic verdict is NO EDGE)."""
    root = tmp_path_factory.mktemp("ts_amended")
    out = root / "out"
    shutil.copytree(train0["out"], out)
    cfg = copy_config(root / "config", train0["cfg"])
    assert summary(out)["results"]["own"]["verdict"] == "NO EDGE"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(S, "measure_timing", quick_timing())
        mp.setattr(D, "downvol_backtest", partial(_fails_in_fold_0, D.downvol_backtest))
        mp.setattr(V, "verdict", _forced_edge)
        assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "other, after the verdict")) == 0
    return {"out": out, "cfg": cfg, "root": root}


def test_an_amendment_run_counts_every_run_and_reports_the_less_favourable_verdict(amended, train0):
    out = amended["out"]
    s0, s1 = summary(out, 0), summary(out, 1)
    n = s1["start"]["settings"]["n_trials"]
    r = s1["results"]
    studies = S.study_dirs(out / "train")
    assert len(studies) == 24 and sum("_a1_" in x for x in studies) == 12
    assert r["trials"]["n_raw"] == 24 * n and r["trials"]["this_run"] == 12 * n
    assert r["trials"]["n_strict"] == 24 * n + 49 + 2400
    assert (
        s1["start"]["trigger"] == "other, after the verdict"
        and s1["start"]["g6_budget"]["max_drawdown_budget"] == 0.35
    )
    line = S.runlog_entries(out / "RUNLOG.jsonl")[-1]
    assert line["run"] == 1 and line["trigger"] == "other, after the verdict"
    # the less favourable verdict and headline of the two runs, both runs' E1 rank p and E2 p listed
    previous = {
        **s0["results"]["reported"],
        "e1_rank_p": s0["results"]["own"]["e1_rank_p"],
        "e2_p": s0["results"]["own"]["e2_p"],
    }
    want = V.reported_verdict(previous, r["own"], "other, after the verdict")
    assert {k: r["reported"][k] for k in ("verdict", "headline", "superseded")} == {
        k: want[k] for k in ("verdict", "headline", "superseded")
    }
    assert "stop_overall" not in r["reported"] and "stop_overall" not in r["own"]
    assert r["reported"]["runs"] == [
        {"run": 0, "e1_rank_p": s0["results"]["own"]["e1_rank_p"], "e2_p": s0["results"]["own"]["e2_p"]},
        {"run": 1, "e1_rank_p": r["own"]["e1_rank_p"], "e2_p": r["own"]["e2_p"]},
    ]
    # run 1 earned the look on its own (forced), run 0 did not: reported beside run 0, run 1 has no look (#58)
    beside = [{"run": 0, **{key: s0["results"]["own"][key] for key in S.OWN_KEYS}}]
    assert r["own"]["verdict"] == "EDGE" and r["own"]["look_earned"] is True
    assert s0["results"]["own"]["look_earned"] is False and s0["results"]["reported"]["look_earned"] is False
    assert s1["start"]["beside"] == beside and r["reported"]["beside"] == beside
    assert (
        r["reported"]["verdict"] == s0["results"]["own"]["verdict"] and r["reported"]["look_earned"] is False
    )
    assert r["pending"] is None  # run 1's own EDGE is not pending E9: it gets no look
    assert r["earlier_runs"]["0"]["verdict"] == s0["results"]["verdict"]
    # G3 and G4 count every study of every run
    a = r["seeds"]["A"]
    oos = pd.read_parquet(out / "train" / "run1" / "oos.parquet")["S_A"]
    rep = overfitting_report(
        {
            "oos_returns": oos,
            "wf_efficiency": a["overfitting_report"]["wf_efficiency"],
            "studies": studies,
            "total_trials": 24 * n,
        },
        out / "train",
    )
    assert a["overfitting_report"] == S.jsonable(rep)
    assert set(pd.read_csv(out / "tracked" / "trials.csv")["run"]) == {0, 1}
    assert set(pd.read_csv(out / "tracked" / "evaluations.csv")["run"]) == {0, 1}


def test_failed_trials_are_reported_with_their_error_and_need_triage_before_the_freeze(
    amended, clean_git, capsys
):
    """Stop rule 4: the phase finishes; every failed trial is listed with Optuna's logged error; no freeze before
    the triage."""
    out, cfg = amended["out"], amended["cfg"]
    r = summary(out, 1)["results"]
    assert r["triage_required"] and r["failed_trials"]
    for f in r["failed_trials"]:
        assert f["study"].endswith("_a1_wf00") and f["state"] == "FAIL" and f["params_crypto_share"] > 0.5
        assert f["fail_reason"].startswith(f"Trial {f['number']} failed with parameters: {{'lookback': ")
        assert f["fail_reason"].endswith("because of the following error: ValueError('an injected failure').")
    assert (
        len(r["failure_log"]) == len(r["failed_trials"])
        and "an injected failure" in r["failure_log"][0]["traceback"]
    )
    trials = pd.read_csv(out / "tracked" / "trials.csv")
    assert (trials["state"] == "FAIL").sum() == len(r["failed_trials"])
    copy = amended["root"] / "copy"
    shutil.copytree(out, copy)
    # --any-verdict: run 1 is reported beside run 0's NO EDGE (stop rule 18), so its look is not earned (#58)
    assert FZ.main(["--out-dir", str(copy), "--config-dir", str(cfg), "--any-verdict"]) == 2
    assert "triage them first" in capsys.readouterr().err and not (copy / "FROZEN.json").exists()
    note = "no code bug: the failure was injected by the test"
    assert (
        FZ.main(["--out-dir", str(copy), "--config-dir", str(cfg), "--any-verdict", "--triaged", note]) == 0
    )
    frozen = json.loads((copy / "FROZEN.json").read_text())
    assert frozen["triage_note"] == note and frozen["run"] == 1


def test_a_third_amendment_run_is_refused(amended, tmp_path, clean_git, capsys):
    out = tmp_path / "out"
    shutil.copytree(amended["out"], out)
    write_start(out, 2, "synthetic", True)
    assert RT.main(train_args(out, amended["cfg"], "--amendment", "3", "--trigger", "b")) == 2
    assert "INCONCLUSIVE" in capsys.readouterr().err


# --------------------------------------------------------------------------------------------- freeze


def test_freeze_refuses_when_the_look_is_not_earned(fresh, clean_git, capsys):
    out, cfg = fresh
    set_look_earned(out, False)
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
    assert {k: f[k] for k in S.frozen_numbers(s["results"])} == S.frozen_numbers(s["results"])
    assert (
        f["panels"]["KRAKEN"]["hash"] == s["panels"]["KRAKEN"]["hash"]
        and f["panels"]["BINANCE"]["rows"] == 1963
    )
    assert (
        f["risk_limits_train_start"] == s["start"]["risk_limits"]
        and f["g6_budget"] == s["start"]["g6_budget"]
    )
    assert f["branch"] == s["start"]["branch"] and f["summary_sha256"] == S.sha256_file(
        out / "train" / "run0" / "summary.json"
    )
    assert f["n_trials_per_study"] == s["start"]["settings"]["n_trials"] and f["seeds"] == {"A": 0, "B": 1}
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2  # once


def test_freeze_refuses_a_changed_hash_and_takes_the_risk_levels_exception(fresh, clean_git, capsys):
    out, cfg = fresh
    set_look_earned(out, True)
    (cfg / "costs.yaml").write_text((cfg / "costs.yaml").read_text() + "# a change\n")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "config/costs.yaml" in capsys.readouterr().err and not (out / "FROZEN.json").exists()
    shutil.copy(CONFIG_DIR / "costs.yaml", cfg / "costs.yaml")
    edit_steady_entry(cfg, "min_cash_pct: 20", "min_cash_pct: 21")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "min_cash" in capsys.readouterr().err
    shutil.copy(CONFIG_DIR / "risk_levels.yaml", cfg / "risk_levels.yaml")
    edit_steady_entry(cfg, "hold_mix_max_rebalances_per_30d: 2", "hold_mix_max_rebalances_per_30d: 3")
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    f = json.loads((out / "FROZEN.json").read_text())
    assert f["deviations"][0]["risk_levels_sha256_now"] == S.sha256_file(cfg / "risk_levels.yaml")
    assert f["g6_budget"]["max_drawdown_budget"] == 0.35  # never rescored


def test_freeze_reports_the_last_run_only_when_it_is_complete(fresh, clean_git, tmp_path, capsys):
    out, cfg = fresh
    set_look_earned(out, True)
    assert FZ.reported_run(out / "train")[0] == 0
    (out / "train" / "run1").mkdir()
    (out / "train" / "run1" / "summary.json").write_text(json.dumps({"status": "crashed: X"}))
    with pytest.raises(S.Refusal, match="run 1, the last train run, is not complete"):
        FZ.reported_run(out / "train")
    assert (
        FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2 and not (out / "FROZEN.json").exists()
    )
    with pytest.raises(S.Refusal, match="no train run"):
        FZ.reported_run(tmp_path / "nothing")
    real = tmp_path / "real" / "train" / "run0"
    real.mkdir(parents=True)
    (real / "summary.json").write_text(
        json.dumps({"status": "complete", "start": {"data": "real"}, "results": {}})
    )
    assert FZ.main(["--out-dir", str(tmp_path / "real"), "--any-verdict"]) == 2
    assert "synthetic dry runs only" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------- the look


def test_the_look_runs_once_and_its_numbers_are_recomputed_from_their_inputs(frozen, tmp_path):
    out, cfg = frozen
    assert RV.main(validate_args(out, cfg)) == 0
    look = json.loads((out / "validate" / "look.json").read_text())
    f = json.loads((out / "FROZEN.json").read_text())
    assert (out / "validate" / "STARTED").is_file()
    assert look["consistency"] == {
        "panel_hashes": {"BINANCE": True, "KRAKEN": True},
        "theta_final_reproduced": {"A": True, "B": True},
    }
    assert look["kept_rows"] == 546
    # E9 by hand: theta_final(A) from row 0, its N0 from its book at t0, its 25 guarded shifts over 78 checks
    K = S.load_study_panel(
        S.SOURCE,
        S.VALIDATE_LAST_CLOSE,
        catalog_dir=tmp_path,
        config_dir=cfg,
        loader=S.synthetic_bar_loader(SEED),
    )
    limits, c1 = sd.steady_limits(cfg), Costs.from_yaml(cfg / "costs.yaml")
    theta = f["theta_final"]["A"]["params"]
    t0 = K.index[2190]
    assert t0 == pd.Timestamp("2023-01-02", tz="UTC")
    run = D.downvol_backtest(theta, K, limits=limits, costs=c1)
    kept = sd.kept_returns(run, t0)
    n0 = sd.kept_returns(
        T.always_in_n0(
            K,
            run.attrs["targets"],
            t0,
            theta["crypto_share"],
            limits=limits,
            costs=c1,
            base_states=run.attrs["z"],
        ),
        t0,
    )
    checks = T.check_closes(K.index[: len(K) - 1], 0, 2190)  # the checks whose orders fill by 2024-07-01
    assert len(checks) == 78
    window = sd.Window(K.index[0], K.index[2189], t0, K.index[-1])
    sched = V.stitched_schedule(K.index, [window], [run.attrs["z"]], [run.attrs["share"]])
    sched = T.Schedule(
        sched.checks[:-1], sched.z[:-1], sched.share[:-1], sched.fold[:-1], sched.head_z, sched.head_share
    )
    np.testing.assert_array_equal(sched.checks, checks)
    q_at, order = run.attrs["q"][sched.checks], lambda u: (np.arange(78) + u) % 78
    q_only = [  # E9's validate shifts are M1's q-only shifts: theta's one s, so VP's whole-schedule shifts too
        sched._replace(z=sched.z[order(u)], share=theta["crypto_share"] * q_at[order(u)])
        for u in range(53, 78)
    ]
    shifts = [_sh(T.run_span(K, sh, limits=limits, costs=c1)["ret"].loc[kept.index]) for sh in q_only]
    assert shifts == [
        _sh(T.run_span(K, sched, limits=limits, costs=c1, u=u)["ret"].loc[kept.index]) for u in range(53, 78)
    ]
    e9 = T.e9_holds(_sh(kept), f["train_sharpe"]["A"], _sh(n0), shifts)
    assert look["E9"] == S.jsonable(
        {
            "holds": e9,
            "sharpe": _sh(kept),
            "train_sharpe_A": f["train_sharpe"]["A"],
            "sharpe_n0": _sh(n0),
            "shift_sharpes": shifts,
            "shift_median": float(np.median(shifts)),
        }
    )
    assert look["criteria"] == {**f["criteria"], "E9": e9}
    own = look["own"]
    assert own["verdict"] == V.verdict(look["criteria"], changes=f["p_changes"])
    assert own["headline"] == S.jsonable(
        V.headline(own["verdict"], {(p["item"], p["point"]): p["value"] for p in f["points"]})
    )
    # stop rule 18: run 0 is reported beside no earlier run, so the look reports its own verdict and headline
    assert look["verdict"] == {"verdict": own["verdict"]["verdict"], "label": own["verdict"]["label"]}
    assert look["headline"] == {"headline": own["headline"]["headline"]}
    assert look["reported"]["beside"] == [] and look["reported"]["own_after_e9"] == {
        "verdict": own["verdict"]["label"],
        "headline": own["headline"]["headline"],
    }
    csv = pd.read_csv(out / "tracked" / "validate.csv").set_index("id")
    assert (
        csv.loc["theta_A", "sharpe"] == pytest.approx(_sh(kept), rel=1e-15, abs=0)
        and len(csv.filter(like="shift_", axis=0)) == 25
    )
    assert [x["run"] for x in S.runlog_entries(out / "RUNLOG.jsonl")] == [0, "validate"]
    assert RV.main(validate_args(out, cfg)) == 2  # no second look
    (out / "validate" / "STARTED").unlink()
    assert RV.main(validate_args(out, cfg)) == 2  # look.json alone also refuses
    copy = out.parent / "copy"
    shutil.copytree(out, copy)
    shutil.rmtree(copy / "validate")
    assert (
        RV.main(validate_args(copy, cfg)) == 2 and not (copy / "validate").exists()
    )  # the RUNLOG holds the look


def test_started_is_written_before_any_validate_bar_and_a_crash_counts(frozen, monkeypatch):
    out, cfg = frozen
    seen = {}

    def spy_factory(seed):
        def loader(*args, **kwargs):
            seen["started"] = (out / "validate" / "STARTED").is_file()
            seen["runlog"] = S.runlog_entries(out / "RUNLOG.jsonl")
            raise KeyError("crash inside the look")

        return loader

    monkeypatch.setattr(S, "synthetic_bar_loader", spy_factory)
    with pytest.raises(KeyError):
        RV.main(validate_args(out, cfg))
    assert seen["started"] and seen["runlog"][-1]["run"] == "validate"
    look = json.loads((out / "validate" / "look.json").read_text())  # the crash is recorded (#58)
    assert (
        look["crashed"] == "KeyError: 'crash inside the look'"
        and look["verdict"]["verdict"] == "INCONCLUSIVE"
    )
    assert RV.main(validate_args(out, cfg)) == 2


@pytest.mark.parametrize(
    "seed, wrap, message",
    [
        (SEED + 1, None, "Stop: the train rows"),  # other bars: the train rows no longer hash
        (SEED, _drop_close("ETH/USD.KRAKEN", "2023-06-01"), "2736 rows, the plan counts 2737"),
    ],
)
def test_a_failed_consistency_check_spends_the_look(frozen, monkeypatch, seed, wrap, message):
    out, cfg = frozen
    if wrap is not None:
        monkeypatch.setattr(S, "synthetic_bar_loader", wrap(S.synthetic_bar_loader))
    assert RV.main(validate_args(out, cfg, seed=seed)) == 3
    look = json.loads((out / "validate" / "look.json").read_text())
    assert look["verdict"]["verdict"] == "INCONCLUSIVE" and message in look["stopped"]
    assert RV.main(validate_args(out, cfg)) == 2


def test_theta_final_must_reproduce_its_logged_returns_at_the_look(fresh, clean_git):
    out, cfg = fresh
    set_look_earned(out, True)
    theta = summary(out)["results"]["theta_final"]["B"]
    path = out / "train" / theta["study"] / "returns" / f"trial_{theta['trial_number']:06d}.parquet"
    logged = pd.read_parquet(path)
    logged.iloc[5, 0] += 1e-12
    logged.to_parquet(path)  # before the freeze, so FROZEN.json records it
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 0
    assert RV.main(validate_args(out, cfg)) == 3
    look = json.loads((out / "validate" / "look.json").read_text())
    assert "does not reproduce" in look["stopped"] and "'A': True, 'B': False" in look["stopped"]


def test_the_look_s_refusals(frozen, monkeypatch, capsys):
    out, cfg = frozen
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(DIRTY))
    assert RV.main([a for a in validate_args(out, cfg)]) == 2
    assert "the git tree is dirty" in capsys.readouterr().err
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
    copy.write_bytes((out / "FROZEN.json").read_bytes())
    data = json.loads((out / "FROZEN.json").read_bytes())
    for key, value in (
        ("points", data["points"][:-1]),
        ("summary_sha256", "0" * 64),
        ("train_sharpe", {"A": 9.0, "B": 0.0}),
    ):
        edited = json.dumps(
            {**data, key: value}
        ).encode()  # the same edit to both copies: certified by nothing
        for path in (out / "FROZEN.json", copy):
            path.write_bytes(edited)
        assert RV.main(validate_args(out, cfg)) == 2
        err = capsys.readouterr().err
        assert ("is not the summary" if key == "summary_sha256" else f"['{key}']") in err, err
    monkeypatch.setattr(S, "read_snapshot", lambda catalog_dir, synthetic: {"snapshot_id": "another"})
    for path in (out / "FROZEN.json", copy):
        path.write_text(json.dumps(data))
    copy.write_bytes((out / "FROZEN.json").read_bytes())
    assert RV.main(validate_args(out, cfg)) == 2
    assert "is not the frozen one" in capsys.readouterr().err
    no_any = [a for a in validate_args(out, cfg) if a != "--any-verdict"]
    for key, edit in (
        (
            "reported",
            {**data["reported"], "look_earned": False},
        ),  # the reported record decides the look (#58)
        ("verdict", {**data["verdict"], "look_earned": False}),  # the own verdict alone: not the summary's
    ):
        for path in (out / "FROZEN.json", copy):
            path.write_text(json.dumps({**data, key: edit}))
        assert RV.main(no_any) == 2
        err = capsys.readouterr().err
        assert ("no validate look" if key == "reported" else "['verdict']") in err, err
    assert not (out / "validate").exists()


def test_the_look_s_real_data_refusals(fresh, clean_git, monkeypatch, capsys):
    out, cfg = fresh
    assert RV.main(validate_args(out, cfg)) == 2
    assert "run freeze.py first" in capsys.readouterr().err
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg), "--any-verdict"]) == 0
    monkeypatch.setattr(S, "DEFAULT_OUT", out)  # a real look in the pinned (here: stand-in) folders
    monkeypatch.setattr(S, "DEFAULT_CATALOG", out.parent / "no-catalog")
    monkeypatch.setattr(S, "HERE", out.parent / "here")
    assert RV.main([]) == 2
    assert "synthetic train run" in capsys.readouterr().err
    assert RV.main(["--allow-dirty"]) == 2
    assert "synthetic dry runs only" in capsys.readouterr().err
    assert not (out / "validate").exists()


# ---------------------------------------------------------------------------------------- A0 and A1


@pytest.fixture(scope="module")
def controls(tmp_path_factory):
    out = tmp_path_factory.mktemp("a0") / "a0"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
        mp.setattr(catalog, "load_bars", _refuse_real_bars)
        mp.setattr(S, "measure_timing", quick_timing())
        assert A0.main(["--out-dir", str(out), "--fast"]) == 0
    return out


def test_a0_s_numbers_are_recomputed_from_its_panels(controls):
    c = json.loads((controls / "controls.json").read_text())
    assert c["start"]["sizes"] == {"panels": 1, "vol_panels": 2, "n_trials": 10, "bootstrap_resamples": 200}
    assert c["start"]["projection"]["budget_minutes"] == 120
    assert c["summary"] == S.jsonable(A0.summarize(c["panels"], c["vol_check"]))
    assert [(p["kind"], p["j"]) for p in c["panels"]] == [("positive", 0), ("negative", 0)]
    limits, c1 = sd.steady_limits(None), Costs.from_yaml()
    # each control panel rebuilt by hand with the logged per-fold choices: E1, E2 and P
    for rec in c["panels"]:
        panel = A0.control_panel(rec["kind"], rec["j"])
        windows = T.fold_windows(panel.index)
        runs = _h0(panel, windows, rec["params"], limits, c1)
        s = _stitch(runs, windows)
        shares = [p["crypto_share"] for p in rec["params"]]
        r0, shifts, w = _span(
            panel, runs, windows, limits, c1, range(53, 260), s.index, shares
        )  # q-only (M1)
        assert w == rec["W"] == 260
        e1 = T.e1_test(r0, shifts, w)
        e2 = T.e2_test(s, _n0(panel, runs, windows, rec["params"], limits, c1), n_resamples=200)
        assert (rec["E1"], rec["e1_rank_p"], rec["E2"], rec["e2"]["p"]) == (
            e1["holds"],
            e1["rank_p"],
            e2["holds"],
            e2["p"],
        )
        power = V.power_count([x.attrs["share"] for x in runs], windows, panel.index)
        assert (rec["P"], rec["changes"]) == (power["holds"], power["total"])
    # the volatility-clustering panels 0 and 1 by hand: the fixed rule (30, 0.60, 0.50), R_0 and 207 shifts (one s,
    # so the q-only shifts are VP's whole-schedule shifts bit for bit)
    for j, logged in enumerate(c["vol_check"]):
        g = T.garch_panel(j)
        path = D.downvol_path(g, 30, 0.60, 0.50)
        gw = T.fold_windows(g.index)
        ends = [g.index.get_loc(x.last) + 1 for x in gw]
        sched = V.stitched_schedule(g.index, gw, [path.z[:e] for e in ends], [path.share[:e] for e in ends])
        keep = np.concatenate([np.flatnonzero((g.index > x.t0) & (g.index <= x.last)) for x in gw])
        series = {
            u: T.run_span(g, sched, limits=limits, costs=c1, u=u)["ret"].to_numpy()[keep]
            for u in [0, *range(53, 260)]
        }
        assert logged == {
            "j": j,
            **S.jsonable({k: T.e1_test(series[0], series, 260)[k] for k in ("holds", "rank_p")}),
        }


def test_a0_summary_rules_by_hand():
    """Section 9: power is E1, E2 and P on the positive panels; a false positive is E1 and E2 on a negative panel; 3 in
    20 is stop rule 15; power below 4 the owner alarm; the clustering panels' E1 rate is a description, no alarm."""

    def panel(kind, e1, e2, p):
        return {"kind": kind, "E1": e1, "E2": e2, "P": p}

    neg = [panel("negative", True, True, True)] * 2 + [panel("negative", True, False, True)]
    pos = [panel("positive", True, True, True)] * 3 + [panel("positive", True, True, False)]
    got = A0.summarize(pos + neg, [{"holds": True}] * 150 + [{"holds": False}] * 50)
    assert (
        got["power"],
        got["false_positives"],
        got["e1_alone"]["negative"],
        got["e2_alone"]["negative"],
    ) == (
        3,
        2,
        3,
        2,
    )
    assert got["stop_rule_15"] is False and got["power_alarm"] is True
    assert got["vol_clustering"] == {
        "panels": 200,
        "e1_passes": 150,
        "pass_rate": 0.75,
        "note": "power where the mechanism is real (a description; no alarm)",
    }
    assert (
        A0.summarize(pos + neg + [panel("negative", True, True, False)], [{"holds": False}])["stop_rule_15"]
        is True
    )
    assert (
        A0.summarize(pos + [panel("negative", True, False, True)] * 9, [{"holds": True}] * 200)[
            "stop_rule_15"
        ]
        is False
    )
    assert A0.summarize(pos * 2, [{"holds": True}])["power_alarm"] is False  # 6 of 8 >= 4
    assert (
        A0.summarize(pos[:3] + [panel("positive", True, True, True)] + neg, [{"holds": False}])["power_alarm"]
        is False
    )


def _no_panel(*args, **kwargs):
    raise AssertionError("A0 built a panel although its guard should have refused")


def test_a0_s_guards(tmp_path, monkeypatch, capsys):
    """Stop rule 17 at 120 CPU-minutes and A0's other refusals; a broken guard fails here at once, never by
    starting the plan's 40 panels and 200 volatility panels (#51's lesson)."""
    monkeypatch.setattr(S, "git_state", lambda repo=S.REPO: dict(CLEAN))
    monkeypatch.setattr(A0, "pipeline", _no_panel)
    monkeypatch.setattr(A0, "vol_check", _no_panel)
    monkeypatch.setattr(S, "measure_timing", quick_timing({**QUICK, "study": 1e4}))
    assert A0.main(["--out-dir", str(tmp_path / "a")]) == 2  # stop rule 17 at 120 CPU-minutes
    assert "stop rule 17" in capsys.readouterr().err and not (tmp_path / "a").exists()
    assert A0.main(["--out-dir", str(tmp_path / "b"), "--workers", "0"]) == 2
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "start.json").write_text("{}")
    assert A0.main(["--out-dir", str(tmp_path / "c"), "--fast"]) == 2
    assert "A0 runs once" in capsys.readouterr().err
    assert A0.main(["--out-dir", str(S.REPO / "scratch-a0")]) == 2 and not (S.REPO / "scratch-a0").exists()
    exactly = {"study": 120 * 60 / 200, "run": 0.0, "bootstrap": 0.0}  # 200 studies: 120 minutes
    assert S.projection({"seconds": exactly}, S.a0_counts(), 120)["allows"]


def test_a1_s_rule_and_its_record(tmp_path, monkeypatch):
    assert A1.rule_n(5.96) == {"N": 200, "ask_owner": False, "twelve_studies_cpu_minutes": 12 * 5.96 / 60}
    assert A1.rule_n(300.0)["N"] == 200  # 12 x 300 s = 60 CPU-minutes exactly
    assert A1.rule_n(400.0)["N"] == 150  # 3600 / (12 x 2 s a trial) = 150
    assert A1.rule_n(1000.0) == {"N": 50, "ask_owner": False, "twelve_studies_cpu_minutes": 200.0}
    assert A1.rule_n(1300.0)["N"] == 25 and A1.rule_n(1300.0)["ask_owner"]
    monkeypatch.setattr(S, "measure_timing", quick_timing())
    assert A1.main(["--out-dir", str(tmp_path / "a1"), "--trials", "4", "--reps", "1"]) == 0
    rec = json.loads((tmp_path / "a1" / "throughput.json").read_text())
    assert rec["study"]["trials"] == 4 and rec["rule"] == A1.rule_n(rec["study"]["cpu_s_per_200"])
    assert rec["projection_run0"] == S.projection(rec["timing"], S.run_counts(), 60)
    assert rec["redo"] == (rec["backtest_typical_median_s"] > 2 * 0.0131)
    assert rec["projection_a0"] == S.projection(rec["timing"], S.a0_counts(), 120)
    assert A1.POINTS == {
        "typical": S.A0_VOL_POINT,
        "busy": {"lookback": 10, "target_vol": 0.30, "crypto_share": 0.6},
    }


def test_the_freeze_refuses_an_amendment_run_whose_runlog_line_has_no_trigger(
    amended, tmp_path, clean_git, capsys
):
    """Stop rule 18: a RUNLOG amendment line without a trigger is refused (the freeze is the gate to the look)."""
    out = tmp_path / "out"
    shutil.copytree(amended["out"], out)
    path = out / "RUNLOG.jsonl"
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    args = ["--out-dir", str(out), "--config-dir", str(amended["cfg"]), "--triaged", "n", "--any-verdict"]
    for trigger in (None, "d"):
        lines[-1]["trigger"] = trigger
        path.write_text("".join(json.dumps(x) + "\n" for x in lines))
        assert FZ.main(args) == 2
        assert (
            "has no line for amendment run 1" in capsys.readouterr().err
            and not (out / "FROZEN.json").exists()
        )
    path.write_text("".join(json.dumps(x) + "\n" for x in lines[:-1]))  # no line for run 1 at all
    assert FZ.main(args) == 2
    assert "has no line for amendment run 1" in capsys.readouterr().err


def test_the_n0_span_and_the_binance_comparison_are_recomputed(rebuilt):
    rb = rebuilt
    r, K, windows, limits, c1 = rb["r"], rb["K"], rb["windows"], rb["limits"], rb["c1"]
    params = r["seeds"]["A"]["params"]
    runs = _h0(K, windows, params, limits, c1)
    kept = _stitch(runs, windows).index
    sched = V.stitched_schedule(
        K.index, windows, [x.attrs["z"] for x in runs], [x.attrs["share"] for x in runs]
    )
    targets, _ = T.span_targets(sched, len(K))
    span = T.from_t0(
        K, targets, windows[0].t0, T.share_targets(params[0]["crypto_share"]), limits=limits, costs=c1
    )
    oos = pd.read_parquet(rb["train"] / "run0" / "oos.parquet")
    np.testing.assert_array_equal(span["ret"].loc[kept].to_numpy(), oos["N0_span"].to_numpy())
    n0 = _n0(K, runs, windows, params, limits, c1)
    s = _stitch(runs, windows)
    later = kept[kept > windows[1].t0]
    k14 = r["e8"]["kraken_folds_1_4"]
    assert k14 == {
        "sharpe": _sh(s.loc[later]),
        "sharpe_n0": _sh(n0.loc[later]),
        "d": _sh(s.loc[later]) - _sh(n0.loc[later]),
    }


def test_overshoot_by_hand():
    limits = {"min_cash": 0.2, "max_coin": 0.6}
    got = S.overshoot([0.61, 0.5, 0.3, 0.2], [0.1, 0.31, 0.3, 0.2], limits)
    assert got == {
        "lowest_cash": 1.0 - 0.5 - 0.31,
        "highest_coin": 0.61,
        "most_crypto": 0.81,
        "closes_in_breach": 2,
    }
    assert S.overshoot([0.0], [0.61], limits)["closes_in_breach"] == 1  # ETH's cap alone (cash 0.39 is fine)
    assert S.overshoot([0.61], [0.0], limits)["closes_in_breach"] == 1  # BTC's cap alone
    assert S.overshoot([0.41], [0.4], limits)["closes_in_breach"] == 1  # the cash floor alone
    assert S.overshoot([0.6 + 5e-10], [0.0], limits)["closes_in_breach"] == 0  # LIMIT_TOL
    assert S.overshoot([0.5], [0.3 + 5e-10], limits)["closes_in_breach"] == 0


def test_theta_final_and_the_stable_region_rechecks_stop(train0, tmp_path):
    out, cfg = train0["out"], train0["cfg"]
    s = summary(out)
    theta = s["results"]["theta_final"]["A"]
    trials = S.trial_table(out / "train", [theta["study"]])
    done = trials[trials["state"] == "COMPLETE"]
    other = int(done.loc[done["number"] != theta["trial_number"], "number"].iloc[0])
    K = S.load_study_panel(
        S.SOURCE,
        S.TRAIN_LAST_CLOSE,
        catalog_dir=tmp_path,
        config_dir=cfg,
        loader=S.synthetic_bar_loader(SEED),
    )
    ctx = {
        "fn1": partial(
            D.downvol_backtest, limits=sd.steady_limits(cfg), costs=Costs.from_yaml(cfg / "costs.yaml")
        ),
        "K": K,
        "train": out / "train",
        "tally": S.Tally(),
    }
    choice = {"params": theta["params"], "trial_number": theta["trial_number"]}
    res = RT.theta_in_sample(ctx, choice, theta["study"], "A")
    assert ctx["tally"].n["rule"] == 1 and res.attrs["share"].shape == (len(K),)
    with pytest.raises(S.Stop, match="does not reproduce its logged trial returns"):
        RT.theta_in_sample(ctx, {**choice, "trial_number": other}, theta["study"], "A")
    RT.neighbourhood(trials, theta["params"])
    with pytest.raises(S.Stop, match="stable region recomputed"):
        RT.neighbourhood(trials, {**theta["params"], "lookback": theta["params"]["lookback"] + 1})


def test_a0_s_control_panels_are_the_plan_s():
    from lab.data.synthetic import shuffled_market, synthetic_market

    market = synthetic_market(2190, seed=1003, start="2017-01-02")
    for kind, want in (("positive", market), ("negative", shuffled_market(market, seed=3))):
        got = A0.control_panel(kind, 3)
        ref = make_panel(want, snapshot_id="synthetic")
        assert sd.panel_hash(got) == sd.panel_hash(ref)
    assert sd.panel_hash(A0.control_panel("positive", 3)) != sd.panel_hash(A0.control_panel("negative", 3))
    assert A0.PLAN_SIZES == A0.Sizes(panels=20, vol_panels=200, n_trials=200, bootstrap_resamples=10_000)
    # the clustering panels are trend-steady's M21 generator (default_rng(10_000 + j)), the rule at (30, 0.60, 0.50)
    assert (
        sd.panel_hash(T.garch_panel(5)) == sd.panel_hash(T.garch_panel(5)) != sd.panel_hash(T.garch_panel(6))
    )
    assert S.A0_VOL_POINT == {"lookback": 30, "target_vol": 0.6, "crypto_share": 0.5}


def test_the_whipsaw_total_counts_each_order_once_and_the_spells_by_hand():
    """INTERPRETATIONS["whipsaw"] and ["episodes"] on a hand-made run (s = 0.3): the first buy (row 2) is not counted;
    the changes on rows 4 (0.15), 6 (0.3) and 8 (0.15) reverse each other within 28 days (two whipsaws sharing the
    order of row 6); row 10's change to 0.075 does not return to 0.3. The total counts each order once (#60): bars 5,
    7 and 9, 2 + 3 + 5 = 10, not the per-whipsaw sum 5 + 8 = 13. The step-back spells are the kept rows with q < 1."""
    idx = pd.date_range("2018-01-01", periods=12, freq="D", tz="UTC")
    share = np.array([0, 0, 0.3, 0.3, 0.15, 0.15, 0.3, 0.3, 0.15, 0.15, 0.075, 0.075])
    q = share / 0.3
    fills = pd.DataFrame(
        [
            (3, "BTC", 0.5),
            (3, "ETH", 0.5),
            (5, "BTC", 2.0),
            (7, "BTC", 3.0),
            (9, "ETH", 5.0),
            (11, "BTC", 7.0),
        ],
        columns=["bar", "asset", "cost"],
    )
    run = pd.DataFrame({"ret": np.zeros(12)}, index=idx)
    run.attrs = {"q": q, "share": share, "fills": fills}
    close = pd.DataFrame(
        {("BTC", "close"): np.linspace(100.0, 111.0, 12), ("ETH", "close"): np.full(12, 50.0)}, index=idx
    )
    ctx = {"windows": [SimpleNamespace(t0=idx[1])], "K": close}
    n0 = pd.DataFrame({"ret": np.full(12, 0.01)}, index=idx)
    got = RT.episodes(ctx, {"runs": [run], "n0_runs": [n0]})
    w = got["whipsaws"]
    assert [(x["first"][:10], x["reversed"][:10], x["cost_usd"]) for x in w["list"]] == [
        ("2018-01-05", "2018-01-07", 2.0 + 3.0),
        ("2018-01-07", "2018-01-09", 3.0 + 5.0),
    ]
    assert (w["count"], w["share"], w["orders"], w["cost_usd"]) == (2, 2 / 4, 3, 2.0 + 3.0 + 5.0)
    spells = got["step_back_spells"]
    assert [(x["first"][:10], x["last"][:10], x["lowest_q"]) for x in spells] == [
        ("2018-01-05", "2018-01-06", 0.5),
        ("2018-01-09", "2018-01-12", 0.25),
    ]
    c = close[("BTC", "close")].to_numpy()
    basket = (1.0 + 0.5 * (c[4] / c[3] - 1.0)) * (1.0 + 0.5 * (c[5] / c[4] - 1.0)) - 1.0
    assert spells[0]["basket_return"] == pytest.approx(basket, rel=1e-15)
    assert spells[1]["regret"] == pytest.approx(
        4 * math.log1p(0.01), rel=1e-15
    )  # N0 earned 1% a day, S nothing


def test_r2_r5_count_the_longest_unbroken_all_usdc_stretch():
    """R5's longest stretch is the longest run of consecutive all-USDC kept rows, not their total (TP's hand break
    S19); R3 counts the kept rows with crypto and at each q (INTERPRETATIONS["r3"])."""
    idx = pd.date_range("2018-01-02", periods=7, freq="D", tz="UTC")
    rows = pd.DataFrame(
        {
            "ret": [0.01, -0.02, 0.0, 0.0, 0.03, 0.0, 0.0],
            "w_BTC": [0.0, 0.0, 0.3, 0.0, 0.0, 0.0, 0.25],
            "w_ETH": [0.0, 0.0, 0.3, 0.0, 0.0, 0.0, 0.0],
        },
        index=idx,
    )
    log = pd.DataFrame({"reason": ["switch", "limit", "limit"]})
    got = S.r2_r5(LIMITS, rows, log, [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.75])
    assert got["R5"] == {"days_all_usdc": 5 / 7, "longest_all_usdc_rows": 3}  # stretches of 2 and 3 rows
    assert got["R2"] == {**S.overshoot(rows["w_BTC"], rows["w_ETH"], LIMITS), "limit_fixes": 2}
    assert got["R3"] == {
        "worst_day": -0.02,
        "day_p1": float(np.percentile(rows["ret"], 1)),
        "days_with_crypto": 2 / 7,
        "days_at_q": {"0": 5 / 7, "0.25": 0.0, "0.5": 0.0, "0.75": 1 / 7, "1": 1 / 7},
    }


# ------------------------------------------------------------ the decision rules by hand (the #47 standard)


def _s_record(**changes) -> dict:
    """A record at S where every item passes, its numbers on the boundaries and separating the wirings: S at 1x
    1.5, at 2x 0.6 (G2), N0 at 2x 0.55 (E4), X's falls deeper than S's on both measures (E3), the plateau steps at
    exactly 0.7 x 1.5, p5 exactly at -0.35, the DSRs at 0.95/0.96 and the PBOs at 0.25/0.2."""
    removal = {
        "e1": {"rank_p": 9 / 208},
        "e2": {"d": 0.1, "p": 0.02},
        "e3": [-0.2, -0.3, -0.25, -0.35],
        "e4": [0.6, 0.5],
    }
    base = {
        "sharpe": 1.5,
        "e1": {"rank_p": 9 / 208},
        "e2": {"d": 0.2, "p": 0.04},
        "e3": {"S": [-0.20, -0.30], "X": [-0.25, -0.35]},
        "e4": {"S_2x": 0.6, "N0_2x": 0.55},
        "e6": {"holds": True},
        "e7": [removal, removal],
        "P": {"holds": True},
        "rep": {"oos_sharpe_annual": 1.5, "dsr_effective_count": 0.96, "pbo_mean": 0.25},
        "active": {"dsr_effective": 0.95, "pbo_mean": 0.2},
        "plateau": [1.5 * 0.7] * 6,
        "g6": {"p5": -0.35},
        "g7": {k: {"sharpe": 1.5, "B1": 1.4, "B2": 1.49} for k in ("full", "best", "two best")},
        "g8": {"split": {"excess": {"bull": 0.0, "bear": 0.1, "sideways": 0.1}, "excess_total": 0.2}},
    }
    return {**base, **changes}


def test_the_items_at_s_by_hand():
    nan = float("nan")
    assert all(v is True for v in RT.s_items(_s_record(), 0.35).values())
    assert set(RT.s_items(_s_record(), 0.35)) == set(T.E5A_ITEMS)

    def item(name, budget=0.35, **changes):
        return RT.s_items(_s_record(**changes), budget)[name]

    assert item("E1", e1={"rank_p": 11 / 208}) is False and item("E1", e1={"rank_p": 10 / 208}) is True
    assert item("E2", e2={"d": 0.0, "p": 0.01}) is False and item("E2", e2={"d": 0.2, "p": 0.05}) is False
    assert item("E3", e3={"S": [-0.20, -0.36], "X": [-0.25, -0.35]}) is False  # p5 deeper than X's
    assert item("E3", e3={"S": [-0.26, -0.30], "X": [-0.25, -0.35]}) is False  # drawdown deeper than X's
    assert item("E3", e3={"S": [-0.25, -0.30], "X": [-0.25, -0.35]}) is False  # equal fails
    assert item("E4", e4={"S_2x": 0.6, "N0_2x": 0.6}) is False
    assert item("G2", e4={"S_2x": 0.5, "N0_2x": 0.4}) is False  # at 2x, not Sharpe(S) at 1x (1.5)
    assert item("G2", e4={"S_2x": 0.5000001, "N0_2x": 0.4}) is True
    assert item("G1", rep={"oos_sharpe_annual": 0.99, "dsr_effective_count": 0.96, "pbo_mean": 0.25}) is False
    assert item("G1", rep={"oos_sharpe_annual": nan, "dsr_effective_count": 0.96, "pbo_mean": 0.25}) is None
    assert item("G3", active={"dsr_effective": 0.9499, "pbo_mean": 0.2}) is False  # the active rows alone
    assert item("G3", rep={"oos_sharpe_annual": 1.5, "dsr_effective_count": 0.94, "pbo_mean": 0.25}) is False
    assert item("G4", active={"dsr_effective": 0.95, "pbo_mean": 0.2501}) is False
    assert item("G4", rep={"oos_sharpe_annual": 1.5, "dsr_effective_count": 0.96, "pbo_mean": 0.26}) is False
    assert item("G5(a)", plateau=[1.05] * 5 + [1.0499]) is False
    assert item("G5(a)", sharpe=-1.0, plateau=[5.0] * 6) is False  # Sharpe(S) <= 0 fails
    assert item("G6", g6={"p5": -0.3500001}) is False and item("G6", budget=None) is False
    assert item("G6", budget=0.36, g6={"p5": -0.3500001}) is True  # the recorded budget, not a typed 0.35
    one = {"full": {"sharpe": 1.5, "B1": 1.4, "B2": 1.6}, "best": {"sharpe": 1.5, "B1": 1.4, "B2": 1.4}}
    assert item("G7", g7=one) is False  # above B1, below B2: "or" would pass
    assert item("G7", g7={"full": {"sharpe": 1.5, "B1": nan, "B2": 1.0}}) is None
    neg = {"split": {"excess": {"bull": -0.01, "bear": 0.11, "sideways": 0.1}, "excess_total": 0.2}}
    assert item("G8-excess", g8=neg) is False
    bad = {
        "e1": {"rank_p": 9 / 208},
        "e2": {"d": 0.1, "p": 0.02},
        "e3": [-0.2, -0.3, -0.25, -0.29],
        "e4": [0.6, 0.5],
    }
    assert item("E7", e7=[_s_record()["e7"][0], bad]) is False  # E3 fails in the second removal
    assert item("E6", e6={"holds": False}) is False and item("P", P={"holds": False}) is False


def test_the_point_rules_by_hand():
    nan = float("nan")

    def v(item, nums, sharpe_s=1.5, budget=0.35):
        return RT.point_value(item, nums, sharpe_s=sharpe_s, budget=budget)

    assert (v("G1", [1.0]), v("G1", [0.999]), v("G1", [nan])) == (True, False, None)
    assert (v("G2", [0.5]), v("G2", [0.5001])) == (False, True)
    assert (v("G3", [0.95]), v("G3", [0.9499])) == (True, False)
    assert (v("G4", [0.25]), v("G4", [0.2501])) == (True, False)
    assert (v("G5", [1.05]), v("G5", [1.0499]), v("G5", [5.0], sharpe_s=-1.0)) == (True, False, False)
    assert (v("G6", [-0.35]), v("G6", [-0.3500001]), v("G6", [-0.1], budget=None)) == (True, False, False)
    assert (
        v("G7", {"sharpe": 1.5, "B1": 1.4, "B2": 1.6}) is False
        and v("G7", {"sharpe": 1.5, "B1": 1.5, "B2": 1.0}) is False
    )
    assert (
        v("G7", {"sharpe": 1.5, "B1": 1.4, "B2": 1.49}) is True
        and v("G7", {"sharpe": nan, "B1": 0, "B2": 0}) is None
    )
    ok = {"excess": {"bull": 0.0, "bear": 0.1, "sideways": 0.1}, "excess_total": 0.2}
    assert (
        v("G8-excess", ok) is True
        and v("G8-excess", {**ok, "excess": {**ok["excess"], "bear": 0.1000001}}) is False
    )
    assert v("R1", {"mean": 2.0, "most": 5}) is True
    assert v("R1", {"mean": 2.0001, "most": 5}) is False and v("R1", {"mean": 1.0, "most": 6}) is False
    assert (v("S(s_k) check", [10 / 208]), v("S(s_k) check", [11 / 208])) == (True, False)
    assert (
        v("S(s_k) check", [0.1, 0.049]),
        v("S(s_k) check", [0.1, 0.05]),
        v("S(s_k) check", [0.0, 0.01]),
    ) == (True, False, False)
    with pytest.raises(ValueError, match="no rule"):
        v("G9", [1.0])


def test_the_train_criteria_and_e5_by_hand():
    items = RT.s_items(_s_record(), 0.35)
    a = {"items": items, "sharpe": 1.5}
    week = {str(d): {"sharpe": 1.05} for d in range(1, 7)} | {
        "daily": {"sharpe": -9.0}
    }  # daily is a description
    e8 = {"e1": {"rank_p": 6 / 156}, "e2": {"d": 0.1, "p": 0.01}}
    crit, e5a = RT.train_criteria(a, a, week, e8)
    assert list(crit) == list(T.CRITERIA) and all(crit.values()) and e5a["holds"]
    assert RT.e5b_holds(1.5, week) and not RT.e5b_holds(1.5, {**week, "6": {"sharpe": 1.0499}})
    assert not RT.e5b_holds(-1.0, {str(d): {"sharpe": 5.0} for d in range(1, 7)})
    assert RT.train_criteria(a, a, {**week, "6": {"sharpe": 1.0499}}, e8)[0]["E5"] is False  # E5(b) alone
    b = {"items": {**items, "G6": False}, "sharpe": 1.5}
    assert RT.train_criteria(a, b, week, e8)[0]["E5"] is False  # E5(a): a gate at S differs between the seeds
    assert RT.train_criteria(a, {**a, "sharpe": 1.2499}, week, e8)[0]["E5"] is False  # Sharpes 0.25 apart
    assert RT.train_criteria(a, {**a, "sharpe": 1.25}, week, e8)[0]["E5"] is True
    assert RT.train_criteria(a, a, week, {**e8, "e1": {"rank_p": 8 / 156}})[0]["E8"] is False
    assert RT.train_criteria(a, a, week, {**e8, "e2": {"d": 0.1, "p": 0.05}})[0]["E8"] is False
    for k in ("E1", "E2", "E3", "E4", "E6", "E7", "P"):
        assert RT.train_criteria({**a, "items": {**items, k: False}}, a, week, e8)[0][k] is False
    assert RT.removal_items(
        {"e1": {"rank_p": 0.04}, "e2": {"d": 1, "p": 0.01}, "e3": [-1, -1, -2, -2], "e4": [1, 0]}
    ) == dict.fromkeys(("E1", "E2", "E3", "E4"), True)
    assert not hasattr(RT, "stop_items") and not hasattr(RT, "level_criteria")  # no stop-loss variant


def test_g6_follows_the_recorded_budget():
    """M19: a hand-made p5 of -0.33 fails G6 under a recorded budget of 0.30 and passes under 0.40."""
    n = _s_record(g6={"p5": -0.33})
    assert RT.s_items(n, 0.30)["G6"] is False and RT.s_items(n, 0.40)["G6"] is True
    assert RT.point_value("G6", [-0.33], sharpe_s=1.0, budget=0.30) is False
    assert RT.point_value("G6", [-0.33], sharpe_s=1.0, budget=0.40) is True


def _orders_differ_when(condition):
    original = D.downvol_backtest

    def vol_backtest(params, bars, *, limits, costs, **kw):
        res = original(params, bars, limits=limits, costs=costs, **kw)
        if condition(params, bars, costs):
            res.attrs["order_hash"] = "another"
        return res

    return vol_backtest


@pytest.mark.parametrize(
    "condition, message",
    [
        (
            lambda p, bars, c: c.pool_fee_bps > 5 and len(bars) == 2190 and p["crypto_share"] in V.ALLOWED_S,
            "grid step s = 0.30 orders differently at 2x",
        ),
        (lambda p, bars, c: c.capital_usd == 500.0, "at a USD 500 book orders differently"),
    ],
)
def test_stop_rule_13_at_the_grid_steps_and_the_book_sizes(
    tmp_path, clean_git, monkeypatch, fast_timing, condition, message
):
    monkeypatch.setattr(D, "downvol_backtest", _orders_differ_when(condition))
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    status = summary(out)["status"]
    assert "stop rule 13" in status and message in status, status


# ---------------------------------------- #58: the code review of the scripts (stop rule 18, A0/A1, leak checks)


def _write_run(train: Path, j: int, status: str, trigger=None, own=None) -> None:
    path = train / f"run{j}" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    results = {} if own is None else {"own": own}
    path.write_text(
        json.dumps({"run": j, "status": status, "start": {"trigger": trigger}, "results": results})
    )


def _own(verdict, headline=None, earned=None, e1=0.5, e2=0.5) -> dict:
    return {
        "verdict": verdict,
        "headline": verdict if headline is None else headline,
        "look_earned": verdict == "EDGE" if earned is None else earned,
        "e1_rank_p": e1,
        "e2_p": e2,
    }


def test_the_reported_chain_by_hand(tmp_path):
    """Stop rule 18 over a chain (INTERPRETATIONS["reported"]): (a)-(c) supersede the previous run alone; "other,
    after the verdict" is reported beside it; the least favourable outcome and look_earned of all of them."""
    train = tmp_path / "train"
    edge = _own("EDGE", "EDGE, NOT A CANDIDATE", e1=0.01, e2=0.02)
    no_edge = _own("NO EDGE (LOW POWER: 3 share changes)", e1=0.4, e2=0.6)
    _write_run(train, 0, "complete", own=no_edge)
    _write_run(train, 1, "complete", trigger=S.OTHER, own=edge)
    assert S.beside_runs(train, 0, None) == []
    assert S.beside_runs(train, 1, S.OTHER) == [{"run": 0, **no_edge}]
    assert S.beside_runs(train, 1, "b") == []
    # run 2 by (a) supersedes run 1 only: run 0, which run 1 was reported beside, stays beside run 2
    assert S.beside_runs(train, 2, "a") == [{"run": 0, **no_edge}]
    assert S.beside_runs(train, 2, S.OTHER) == [{"run": 0, **no_edge}, {"run": 1, **edge}]
    _write_run(train, 1, "complete", trigger="c", own=edge)
    assert S.beside_runs(train, 2, S.OTHER) == [{"run": 1, **edge}] and S.beside_runs(train, 2, "b") == []
    _write_run(train, 1, "complete", trigger=None, own=edge)
    with pytest.raises(S.Refusal, match="amendment run 1 has no trigger"):
        S.beside_runs(train, 2, "a")
    _write_run(train, 1, "crashed: KeyError", trigger=S.OTHER)
    with pytest.raises(S.Refusal, match="run 1 has no verdict"):
        S.beside_runs(train, 2, S.OTHER)
    assert S.beside_runs(train, 2, "a") == [{"run": 0, **no_edge}]  # a crash is rerun by (a); run 0 stays
    # the combination
    cand = _own("EDGE", "CANDIDATE FOR AUDIT")
    got = S.combine_reported([{"run": 0, **edge}], cand)
    assert got == {"verdict": "EDGE", "headline": "EDGE, NOT A CANDIDATE", "look_earned": True}
    got = S.combine_reported([{"run": 0, **no_edge}, {"run": 1, **edge}], cand)
    assert got == {"verdict": no_edge["verdict"], "headline": no_edge["headline"], "look_earned": False}
    assert S.combine_reported([], cand) == {k: cand[k] for k in ("verdict", "headline", "look_earned")}
    assert S.combine_reported([], {**cand, "look_earned": False})["look_earned"] is False
    assert S.combine_reported([{"run": 0, **edge}], {**cand, "look_earned": "yes"})["look_earned"] is False
    assert (
        S.combine_reported([{"run": 0, **_own("NO EDGE")}], no_edge)["verdict"] == no_edge["verdict"]
    )  # tie: later
    assert S.outcome_base(no_edge["verdict"], T.VERDICT_ORDER) == "NO EDGE"
    assert [S.outcome_base(v, T.VERDICT_ORDER) for v in ("EDGE", "INCONCLUSIVE")] == ["EDGE", "INCONCLUSIVE"]
    with pytest.raises(ValueError, match="unknown outcome"):
        S.outcome_base("EDGES", T.VERDICT_ORDER)
    # reported_block: an earlier run that crashed has no results and lists nothing (it used to raise KeyError)
    train2 = tmp_path / "train2"
    _write_run(train2, 0, "crashed: X")
    block = RT.reported_block(train2, 1, cand, {"beside": [], "trigger": "a"})
    assert block == {
        **S.combine_reported([], cand),
        "superseded": True,
        "trigger": "a",
        "beside": [],
        "runs": [{"run": 1, "e1_rank_p": 0.5, "e2_p": 0.5}],
    }
    block0 = RT.reported_block(train2, 0, cand, {"beside": [], "trigger": None})
    assert block0["superseded"] is None and block0["runs"] == [{"run": 0, "e1_rank_p": 0.5, "e2_p": 0.5}]
    _write_run(train, 1, "complete", trigger=S.OTHER, own=edge)
    start = {"beside": S.beside_runs(train, 2, S.OTHER), "trigger": S.OTHER}
    block = RT.reported_block(train, 2, cand, start)
    assert (
        block["superseded"] is False
        and block["look_earned"] is False
        and block["runs"]
        == [
            {"run": 0, "e1_rank_p": 0.4, "e2_p": 0.6},
            {"run": 1, "e1_rank_p": 0.01, "e2_p": 0.02},
            {"run": 2, "e1_rank_p": 0.5, "e2_p": 0.5},
        ]
    )


def test_an_other_trigger_needs_a_verdict_and_the_start_record_fixes_the_beside_runs(
    tmp_path, clean_git, monkeypatch, capsys, fast_timing
):
    cfg = copy_config(tmp_path / "config")
    out = tmp_path / "out"
    write_start(out, 0, "synthetic", True, status="crashed: ValueError: x")
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", S.OTHER)) == 2
    assert "run 0 has no verdict" in capsys.readouterr().err and not (out / "train" / "run1").exists()
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "a")) == 2  # no risk limits recorded
    assert "G6 needs run 0's train-start reading" in capsys.readouterr().err
    path = out / "train" / "run0" / "summary.json"
    data = json.loads(path.read_text())
    data["start"]["risk_limits"] = S.jsonable(sd.steady_limits(cfg))
    path.write_text(json.dumps(data))

    def stop(args, summary, run_dir, ctx, settings):
        raise S.Stop("enough")

    monkeypatch.setattr(RT, "train_phase", stop)
    assert RT.main(train_args(out, cfg, "--amendment", "1", "--trigger", "a")) == 3  # a crash is rerun by (a)
    start = summary(out, 1)["start"]
    assert start["beside"] == [] and start["trigger"] == "a" and start["prior_amendments"] is None
    assert start["g6_budget"]["max_drawdown_budget"] == 0.35


def test_a_run_0_no_edge_holds_back_an_other_amendment_s_edge(amended, tmp_path, clean_git, capsys):
    """Stop rules 8 and 18: run 0 NO EDGE, amendment run 1 ("other, after the verdict") EDGE on its own: no freeze and
    no look. The same run 1 by trigger (b) supersedes run 0, and freezes."""
    out = tmp_path / "out"
    shutil.copytree(amended["out"], out)
    cfg = amended["cfg"]
    base = ["--out-dir", str(out), "--config-dir", str(cfg), "--triaged", "the injected failures"]
    assert FZ.main(base) == 2
    err = capsys.readouterr().err
    assert "no validate look" in err and "beside runs [0]" in err and not (out / "FROZEN.json").exists()
    assert FZ.main([*base, "--any-verdict"]) == 0  # synthetic only
    no_any = [a for a in validate_args(out, cfg) if a != "--any-verdict"]
    assert RV.main(no_any) == 2
    assert "no validate look" in capsys.readouterr().err and not (out / "validate").exists()
    # trigger (b): run 1 supersedes run 0, is reported alone, and freezes
    copy = tmp_path / "copy"
    shutil.copytree(amended["out"], copy)
    path = copy / "train" / "run1" / "summary.json"
    data = json.loads(path.read_text())
    data["start"].update(trigger="b", beside=[])
    own = data["results"]["own"]
    data["results"]["reported"].update(
        {k: own[k] for k in ("verdict", "headline", "look_earned")}, trigger="b", beside=[]
    )
    path.write_text(json.dumps(data))
    runlog = copy / "RUNLOG.jsonl"
    lines = [json.loads(x) for x in runlog.read_text().splitlines()]
    lines[-1]["trigger"] = "b"
    runlog.write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert S.beside_runs(copy / "train", 1, "b") == []
    assert (
        FZ.main(["--out-dir", str(copy), "--config-dir", str(cfg), "--triaged", "the injected failures"]) == 0
    )
    assert json.loads((copy / "FROZEN.json").read_text())["reported"]["look_earned"] is True


def test_the_freeze_checks_the_reported_record_and_the_beside_runs(
    amended, fresh, tmp_path, clean_git, capsys
):
    out, cfg = fresh
    path = out / "train" / "run0" / "summary.json"
    data = json.loads(path.read_text())
    data["results"]["reported"]["look_earned"] = True  # not the rule applied to its own record (NO EDGE)
    path.write_text(json.dumps(data))
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "is not its own record combined" in capsys.readouterr().err and not (out / "FROZEN.json").exists()
    copy = tmp_path / "copy"
    shutil.copytree(amended["out"], copy)
    set_look_earned(copy, True, k=0)  # run 0's summary changed after run 1 recorded it beside
    args = ["--out-dir", str(copy), "--config-dir", str(amended["cfg"]), "--triaged", "n", "--any-verdict"]
    assert FZ.main(args) == 2
    assert "an earlier summary changed" in capsys.readouterr().err and not (copy / "FROZEN.json").exists()


def test_with_both_runs_earned_the_look_reports_the_less_favourable_headline(
    amended, tmp_path, clean_git, monkeypatch
):
    """Stop rule 18 at the look: run 1 ("other") CANDIDATE FOR AUDIT after E9, run 0 EDGE, NOT A CANDIDATE: the look
    reports EDGE, NOT A CANDIDATE, with run 1's own values next to it."""
    out = tmp_path / "out"
    shutil.copytree(amended["out"], out)
    cfg = amended["cfg"]
    set_verdict(out, "EDGE", True, k=0)
    s0 = summary(out, 0)
    s0["results"]["own"]["headline"] = s0["results"]["reported"]["headline"] = "EDGE, NOT A CANDIDATE"
    (out / "train" / "run0" / "summary.json").write_text(json.dumps(s0))
    path = out / "train" / "run1" / "summary.json"
    data = json.loads(path.read_text())
    r = data["results"]
    r["criteria"] = dict.fromkeys(r["criteria"], True)
    for p in r["points"]:
        p["value"] = True
    beside = [{"run": 0, **{k: s0["results"]["own"][k] for k in S.OWN_KEYS}}]
    data["start"]["beside"] = beside
    r["reported"]["beside"] = beside
    path.write_text(json.dumps(data))
    set_verdict(out, "EDGE", True, k=1)
    r = summary(out, 1)["results"]
    assert (
        r["own"]["headline"] == "CANDIDATE FOR AUDIT" and r["reported"]["headline"] == "EDGE, NOT A CANDIDATE"
    )
    assert r["reported"]["look_earned"] is True
    assert (
        FZ.main(["--out-dir", str(out), "--config-dir", str(cfg), "--triaged", "the injected failures"]) == 0
    )
    monkeypatch.setattr(T, "e9_holds", lambda *args, **kwargs: True)
    assert RV.main([a for a in validate_args(out, cfg) if a != "--any-verdict"]) == 0
    look = json.loads((out / "validate" / "look.json").read_text())
    assert (
        look["own"]["verdict"]["label"] == "EDGE"
        and look["own"]["headline"]["headline"] == "CANDIDATE FOR AUDIT"
    )
    assert look["verdict"] == {"verdict": "EDGE", "label": "EDGE"}
    assert look["headline"] == {"headline": "EDGE, NOT A CANDIDATE"}
    assert look["reported"]["beside"] == beside and look["reported"]["trigger"] == S.OTHER
    assert look["reported"]["own_after_e9"]["headline"] == "CANDIDATE FOR AUDIT"


def test_prior_amendments_by_hand(tmp_path):
    """INTERPRETATIONS["prior_amendments"]: exactly one A1 line ('- **A1' or '- **Amendment A1') with this build's N,
    exactly one A0 line with no alarm (both phrases) or an owner decision on file; only inside section 15."""
    (tmp_path / "reports" / "director").mkdir(parents=True)
    (tmp_path / "reports" / "director" / "2026-12-01-a0.md").write_text("decision")
    a1 = "- **A1:** (2026-12-01) N = 200 trials per study.\n"
    ok0 = "- **A0:** (2026-12-01) stop rule 15: no alarm; power: no alarm.\n"
    decided = "- **A0:** (2026-12-01) Power 2 of 20; owner decision: `reports/director/2026-12-01-a0.md`.\n"

    def check(rows, n=200, text=None):
        return S.prior_amendments(_plan(rows) if text is None else text, n, repo=tmp_path)

    assert check(a1 + ok0) == {"A1": a1.strip(), "A0": ok0.strip(), "owner_decision": None}
    assert check(a1 + decided)["owner_decision"] == "reports/director/2026-12-01-a0.md"
    long = "- **Amendment A1 (2026-12-01).** N = 200.\n- **Amendment A0 (2026-12-01).** stop rule 15: no alarm; power: no alarm.\n"
    assert check(long)["A1"].startswith("- **Amendment A1")
    placeholders = (
        "- **A1:** the throughput timing (before run 0).\n- **A0:** the procedure controls (before run 0).\n"
    )
    for rows, n, match in (
        ("", 200, "exactly one '- \\*\\*A1' line"),
        (ok0, 200, "exactly one '- \\*\\*A1' line"),
        (a1 + a1 + ok0, 200, "found 2"),
        (a1 + "- **Amendment A1 (2026-12-02).** N = 200.\n" + ok0, 200, "found 2"),  # a second line beside it
        (a1, 200, "exactly one '- \\*\\*A0' line"),
        (a1 + ok0, 150, "does not say 'N = 150'"),
        (a1.replace("N = 200", "N = 2000") + ok0, 200, "does not say 'N = 200'"),
        (a1.replace("N = 200", "N=200") + ok0, 200, "does not say 'N = 200'"),
        (a1 + "- **A0:** stop rule 15: no alarm.\n", 200, "says neither"),
        (a1 + "- **A0:** power: no alarm.\n", 200, "says neither"),
        (a1 + "- **A0:** Ran; see the owner.\n", 200, "says neither"),
        (a1 + decided.replace("2026-12-01-a0", "2026-12-02-a0"), 200, "does not exist"),
        (a1 + "- **A01:** stop rule 15: no alarm; power: no alarm.\n", 200, "A0' line"),
        (placeholders, 200, "does not say 'N = 200'"),  # the committed plan's placeholders refuse
    ):
        with pytest.raises(S.Refusal, match=match):
            check(rows, n)
    outside = f"{a1}{ok0}" + _plan("")  # rows before section 15 do not count
    with pytest.raises(S.Refusal, match="exactly one"):
        check("", text=outside)
    with pytest.raises(S.Refusal, match="exactly one"):
        check("", text=_plan("", after=a1 + ok0))  # nor rows after it (section 17)
    with pytest.raises(S.Refusal, match="no section 15"):
        check("", text=a1 + ok0)


def test_stand_in_plans_hold_amendments_a1_and_a0_once(tmp_path, monkeypatch):
    """#59: the real-data stand-in plan holds exactly one A1 and one A0 line, whether the plan it is built from holds
    placeholders or records; `without_prior_rows` drops those lines (continuation lines included) and nothing else."""
    for source in (stand_in_plan(), stand_in_plan(PRIOR_ROWS)):  # placeholders, and A1 and A0 written
        assert len([ln for ln in S.amendments_section(source).splitlines() if ln.startswith("- **A1")]) == 1
        assert without_prior_rows(source) == without_prior_rows(stand_in_plan())
    base = without_prior_rows(stand_in_plan())
    rows = (
        "- **A1:** (2026-12-01) N = 200 on the first line,\n  and a continuation line.\n"
        "- **A01.** not an A0 line\n"
        "- **Amendment run 1 (2026-12-01).** not an A0 or A1 line\n"
        "- **Amendment A0 (2026-12-01).** stop rule 15: no alarm; power: no alarm.\n"
    )
    kept = "- **A01.** not an A0 line\n- **Amendment run 1 (2026-12-01).** not an A0 or A1 line\n"
    assert without_prior_rows(plan_with(rows, base)) == plan_with(kept, base)
    assert without_prior_rows(base) == base
    section = S.amendments_section(base)
    assert "\n- **A1" not in section and "\n- **A0" not in section
    real = tmp_path / "PLAN.md"
    real.write_text(plan_with(PRIOR_ROWS, base))  # a plan once A1 and A0 are written into it
    monkeypatch.setattr(S, "PLAN", real)
    real_folders(monkeypatch, tmp_path / "stand-in")
    got = S.prior_amendments(S.PLAN.read_text(), S.PLAN_SETTINGS.n_trials)
    assert (got["A1"], got["A0"]) == tuple(PRIOR_ROWS.splitlines())


def test_a_real_run_needs_amendments_a1_and_a0_first(train0, tmp_path, clean_git, monkeypatch, capsys):
    """Section 15, order of work step 4: a real run 0 refuses (exit 2, nothing written) until A1 (with this build's N)
    and A0 (no alarm, or the owner's written decision) are in PLAN.md. Dry runs are exempt. Every plan here is a
    stand-in (#68: never today's committed plan)."""
    out, catalog_dir = real_folders(monkeypatch, tmp_path)
    plan = tmp_path / "PLAN2.md"
    monkeypatch.setattr(S, "PLAN", plan)
    real = without_prior_rows(stand_in_plan())
    placeholders = stand_in_plan(PLACEHOLDERS)  # the plan as committed before A1 and A0 ran
    for text, match in (
        (placeholders, "does not say 'N = 200'"),
        (real, "exactly one '- **A1' line"),  # no A1 or A0 line at all (#59)
        (plan_with(PRIOR_ROWS.replace("N = 200", "N = 150"), real), "does not say 'N = 200'"),
        (plan_with(PRIOR_ROWS.replace("power: no alarm", "power 2 of 20"), real), "says neither"),
        (plan_with(PRIOR_ROWS + PRIOR_ROWS, real), "found 2"),
    ):
        plan.write_text(text)
        assert RT.main([]) == 2
        assert match in capsys.readouterr().err
        assert not out.exists() and not (tmp_path / "here").exists()
    plan.write_text(plan_with(PRIOR_ROWS, real))
    assert RT.main([]) == 2  # past A0 and A1: no SNAPSHOT.json here
    assert "SNAPSHOT.json" in capsys.readouterr().err and not out.exists()
    assert summary(train0["out"])["start"]["prior_amendments"] is None  # the dry run 0 ran without the rows


def test_a0_runs_the_plan_s_n(monkeypatch):
    """One N for A0 and run 0: A0's sizes take study.PLAN_SETTINGS' trials and resamples (amendment A1 sets N)."""
    assert (A0.PLAN_SIZES.n_trials, A0.PLAN_SIZES.bootstrap_resamples) == (
        S.PLAN_SETTINGS.n_trials,
        S.PLAN_SETTINGS.bootstrap_resamples,
    )
    monkeypatch.setattr(S, "PLAN_SETTINGS", S.Settings(n_trials=150, bootstrap_resamples=777))
    spec = importlib.util.spec_from_file_location("downvol_steady_controls_n150", HERE / "controls.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # dataclasses read the module while it is built
    spec.loader.exec_module(module)
    assert module.PLAN_SIZES.n_trials == 150 and module.PLAN_SIZES.bootstrap_resamples == 777


def test_the_train_run_never_asks_for_or_receives_a_bar_after_the_last_train_close(
    tmp_path, clean_git, monkeypatch, fast_timing
):
    """Section 3 and hard rule 5: the train run reads no validate bar, not even one it would cut away later. Every
    loader call asks for the train window only, and nothing it returns closes after 2023-01-01."""
    calls = []
    original = S.synthetic_bar_loader

    def factory(seed):
        inner = original(seed)

        def loader(*args, **kwargs):
            bars = inner(*args, **kwargs)
            calls.append((args[0], kwargs.get("end"), bars.index.max()))
            return bars

        return loader

    def enough(*args, **kwargs):
        raise S.Stop("enough: the panels are loaded")

    monkeypatch.setattr(S, "synthetic_bar_loader", factory)
    monkeypatch.setattr(RT, "walk_forward", enough)  # the first call after the panels load
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    assert sorted(c[0] for c in calls) == sorted(S._SYNTHETIC_IDS)
    for name, end, last in calls:
        assert end == S.TRAIN_LAST_CLOSE, (name, end)
        assert last <= S.TRAIN_LAST_CLOSE, (name, last)
    assert summary(out)["status"] == "stopped: Stop: enough: the panels are loaded"


def test_the_final_study_is_seeded_seed_plus_5000(tmp_path, clean_git, monkeypatch, fast_timing):
    """Section 7: the final study gets seed + 5000 (hard rule 7: the seed recorded is the seed used)."""
    seen = {}

    def spy(name, fn, specs, panel, out_dir, cfg_, context):
        seen[name] = (cfg_.seed, context["seed"])
        raise S.Stop("enough")

    monkeypatch.setattr(RT, "run_study", spy)
    out = tmp_path / "out"
    assert RT.main(train_args(out, copy_config(tmp_path / "config"))) == 3
    assert seen == {f"{S.study_tag(S.SEEDS['A'], 0)}_final": (S.SEEDS["A"] + 5000, S.SEEDS["A"])}


def test_the_look_s_folder_alone_refuses_a_second_look(frozen):
    """Section 13's second guard: validate/STARTED or look.json refuses a look even when the RUNLOG no longer holds
    the first one (a reverted tracked RUNLOG), and a look that crashed (STARTED alone) counts."""
    out, cfg = frozen
    assert RV.main(validate_args(out, cfg)) == 0
    runlog = out / "RUNLOG.jsonl"
    kept = [x for x in runlog.read_text().splitlines() if json.loads(x).get("script") != "run_validate.py"]
    runlog.write_text("".join(x + "\n" for x in kept))
    before = S.tree_hashes(out / "validate")
    assert RV.main(validate_args(out, cfg)) == 2  # STARTED and look.json
    (out / "validate" / "look.json").unlink()
    assert RV.main(validate_args(out, cfg)) == 2  # STARTED alone
    assert not (out / "validate" / "look.json").exists()
    assert S.tree_hashes(out / "validate") == {k: v for k, v in before.items() if k != "look.json"}
    assert runlog.read_text().splitlines() == kept


def test_an_inconclusive_verdict_earns_no_freeze_and_no_look(fresh, clean_git, capsys):
    """Stop rule 8: INCONCLUSIVE (E1 and E2 hold, but P or one of E3-E8 fails) earns no look, like NO EDGE."""
    out, cfg = fresh
    set_verdict(out, "INCONCLUSIVE", False)
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg)]) == 2
    assert "no validate look" in capsys.readouterr().err and not (out / "FROZEN.json").exists()
    assert FZ.main(["--out-dir", str(out), "--config-dir", str(cfg), "--any-verdict"]) == 0  # a dry run may
    assert RV.main([a for a in validate_args(out, cfg) if a != "--any-verdict"]) == 2
    assert "no validate look" in capsys.readouterr().err and not (out / "validate").exists()


def test_correlations_read_the_other_steady_studies_last_complete_run(tmp_path, monkeypatch):
    """INTERPRETATIONS["correlations"]: column S_A of oos.parquet of each study's last complete run (a later crashed
    run or an unreadable summary is skipped); None on synthetic data or when no run is found."""
    idx = pd.date_range("2018-01-03", periods=6, freq="D", tz="UTC")
    s = pd.Series([0.01, -0.02, 0.03, 0.0, 0.01, -0.01], index=idx)
    other = pd.Series([0.02, -0.01, 0.01, 0.01, 0.0, -0.02], index=idx)
    base = tmp_path / "results" / "trend-steady" / "train"
    for j, status, values in (
        (0, "complete", other),
        (1, "complete", other * -1.0),
        (2, "crashed: X", other),
    ):
        (base / f"run{j}").mkdir(parents=True)
        (base / f"run{j}" / "summary.json").write_text(json.dumps({"status": status}))
        pd.DataFrame({"S_A": values}).to_parquet(base / f"run{j}" / "oos.parquet")
    (base / "run3").mkdir()
    (base / "run3" / "summary.json").write_text("not json")
    vol = tmp_path / "results" / "vol-steady" / "train" / "run0"  # the study this one was chosen after (W1)
    vol.mkdir(parents=True)
    (vol / "summary.json").write_text(json.dumps({"status": "complete"}))
    pd.DataFrame({"S_A": other.iloc[1:]}).to_parquet(
        vol / "oos.parquet"
    )  # one close fewer: the common closes
    monkeypatch.setattr(S, "REPO", tmp_path)
    assert RT.stored_s_a("trend-steady", idx).tolist() == (other * -1.0).tolist()  # run 1, the last complete
    assert RT.stored_s_a("rebalance-steady", idx) is None
    b = {"S": s, "N0": s * 0.5}
    ctx = {"data": "real", "B1": other, "B2": other * 2.0}
    got = RT.correlations(ctx, b)
    assert (
        got["trend_steady_S_A"] == float(np.corrcoef(s, -other)[0, 1]) and got["rebalance_steady_S_A"] is None
    )
    assert got["N0"] == pytest.approx(1.0) and got["B1"] == float(np.corrcoef(s, other)[0, 1])
    assert got["vol_steady_S_A"] == float(np.corrcoef(s.iloc[1:], other.iloc[1:])[0, 1])
    assert RT.correlations({**ctx, "data": "synthetic"}, b)["trend_steady_S_A"] is None
