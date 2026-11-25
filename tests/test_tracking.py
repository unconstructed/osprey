"""MLflow logging of search studies (``lab/tracking/mlflow_log.py``; AGENTS.md "Running many simulations", rule 4).

Every finished trial of a study becomes one MLflow run under one parent run per study, with the trial's params,
metrics and state and the study's strategy, window, snapshot id, git commit and seed; failed trials too. Logging
is idempotent, a resumed study adds only its new trials, and a trial still running is left for later.
Synthetic bars, ``tmp_path`` stores and ``n_workers=1`` searches only.
"""

from __future__ import annotations

import json
import math
import runpy
import sys
import warnings

import optuna
import pytest
from mlflow.tracking import MlflowClient

from lab.data.synthetic import synthetic_market
from lab.runner.reference import dip_buy
from lab.search.space import Param
from lab.search.study import SearchConfig, _storage, load_trials, run_study
from lab.tracking import mlflow_log as ml

SPECS = [Param("drop", "float", 0.03, 0.25), Param("lookback", "int", 2, 20)]
CONTEXT = {"strategy": "dip-buy-balanced", "snapshot_id": "0123456789abcdef", "git_commit": "abc1234"}


def flaky(params, bars):
    """dip_buy that fails for odd lookbacks, so a study holds failed trials."""
    if params["lookback"] % 2:
        raise ValueError("odd lookback")
    return dip_buy(params, bars)


@pytest.fixture(scope="module")
def bars():
    return synthetic_market(500, seed=4)["BTC"]


def uri(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'mlflow.db'}"


def study_runs(store: str, name: str):
    client = MlflowClient(store)
    exp = client.get_experiment_by_name(name)
    runs = client.search_runs([exp.experiment_id], max_results=1000)
    parents = [r for r in runs if r.data.tags["osprey.kind"] == "study"]
    trials = {int(r.data.tags["osprey.trial"]): r for r in runs if r.data.tags["osprey.kind"] == "trial"}
    return parents, trials


def test_every_finished_trial_is_one_run_with_its_params_metrics_state_and_context(tmp_path, bars):
    cfg = SearchConfig(n_trials=10, n_workers=1, seed=3)
    table = run_study("s", flaky, SPECS, bars, tmp_path, cfg, context=CONTEXT)
    assert set(table["state"]) == {"COMPLETE", "FAIL"}  # the drawn lookbacks are both odd and even
    store = uri(tmp_path)
    counts = ml.log_study("s", tmp_path, store)
    assert counts["logged"] == 10 and counts["already_logged"] == 0 and counts["unfinished"] == 0
    parents, trials = study_runs(store, "s")
    assert len(parents) == 1 and sorted(trials) == list(range(10))
    parent = parents[0]
    assert parent.data.params["config_seed"] == "3" and parent.data.params["config_n_trials"] == "10"
    study = optuna.load_study(study_name="s", storage=_storage(tmp_path / "s" / "study.journal"))
    for t in study.trials:
        run = trials[t.number]
        tags = run.data.tags
        assert tags["mlflow.parentRunId"] == parent.info.run_id
        assert tags["osprey.state"] == t.state.name
        assert tags["osprey.strategy"] == "dip-buy-balanced"
        assert tags["osprey.snapshot_id"] == "0123456789abcdef" and tags["osprey.git_commit"] == "abc1234"
        assert tags["osprey.seed"] == "3"
        assert tags["osprey.window"] == f"{bars.index[0]} .. {bars.index[-1]}"
        assert run.data.params == {k: str(v) for k, v in t.params.items()}
        if t.state == optuna.trial.TrialState.COMPLETE:
            assert run.info.status == "FINISHED"
            m = run.data.metrics
            assert m["value"] == t.value and m["n_trades"] == t.user_attrs["n_trades"]
            sharpe = t.user_attrs["sharpe"]
            assert ("sharpe" in m) == math.isfinite(sharpe) and m.get("sharpe", sharpe) == sharpe
            for i, s in enumerate(t.user_attrs["block_sharpes"]):
                assert m[f"block_sharpe_{i}"] == s
        else:
            assert run.info.status == "FAILED" and run.data.metrics == {}
    assert len(table) == len(trials)  # the trials table and MLflow hold the same trials


def test_logging_again_adds_only_new_trials_and_leaves_running_ones(tmp_path, bars):
    store = uri(tmp_path)
    cfg = SearchConfig(n_trials=4, n_workers=1, seed=1)
    run_study("r", dip_buy, SPECS, bars, tmp_path, cfg, context=CONTEXT)
    assert ml.log_study("r", tmp_path, store)["logged"] == 4
    again = ml.log_study("r", tmp_path, store)
    assert again["logged"] == 0 and again["already_logged"] == 4
    run_study("r", dip_buy, SPECS, bars, tmp_path, cfg, context=CONTEXT)  # resumed: 4 more trials
    study = optuna.load_study(study_name="r", storage=_storage(tmp_path / "r" / "study.journal"))
    study.ask()  # a trial still running (a worker mid-backtest)
    resumed = ml.log_study("r", tmp_path, store)
    assert resumed == {**resumed, "logged": 4, "already_logged": 4, "unfinished": 1}
    parents, trials = study_runs(store, "r")
    assert len(parents) == 1 and sorted(trials) == list(range(8))


def test_pages_of_runs_are_all_read(tmp_path, bars, monkeypatch):
    store = uri(tmp_path)
    run_study("p", dip_buy, SPECS, bars, tmp_path, SearchConfig(n_trials=5, n_workers=1), context=CONTEXT)
    ml.log_study("p", tmp_path, store)
    monkeypatch.setattr(ml, "PAGE", 2)  # 6 runs over 3 pages, then nothing is logged twice
    assert ml.log_study("p", tmp_path, store)["already_logged"] == 5
    assert len(study_runs(store, "p")[1]) == 5


def test_context_not_recorded_is_tagged_unrecorded(tmp_path, bars):
    store = uri(tmp_path)
    run_study("u", dip_buy, SPECS, bars, tmp_path, SearchConfig(n_trials=2, n_workers=1))
    ml.log_study("u", tmp_path, store, experiment="other-name")
    client = MlflowClient(store)
    exp = client.get_experiment_by_name("other-name")
    for run in client.search_runs([exp.experiment_id]):
        for key in ("strategy", "snapshot_id", "git_commit"):
            assert run.data.tags[f"osprey.{key}"] == ml.UNRECORDED


def test_a_study_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="run the study first"):
        ml.log_study("missing", tmp_path, uri(tmp_path))


def test_run_and_log_runs_the_study_then_logs_it(tmp_path, bars):
    store = uri(tmp_path)
    table = ml.run_and_log(
        "a", dip_buy, SPECS, bars, tmp_path, SearchConfig(n_trials=3, n_workers=1), CONTEXT, store
    )
    assert len(table) == 3 and len(study_runs(store, "a")[1]) == 3
    assert table.equals(load_trials("a", tmp_path))


def test_the_command_line_logs_a_study(tmp_path, bars, capsys, monkeypatch):
    run_study("c", dip_buy, SPECS, bars, tmp_path, SearchConfig(n_trials=2, n_workers=1), context=CONTEXT)
    store = f"sqlite:///{tmp_path / 'new' / 'dir' / 'mlflow.db'}"  # its folder is created
    counts = ml.main([str(tmp_path), "c", "--uri", store])
    assert counts["logged"] == 2 and json.loads(capsys.readouterr().out)["logged"] == 2
    # another backend (Postgres, for several machines) is passed on as given and no folder is made for it
    seen = []
    monkeypatch.setattr(
        ml, "log_study", lambda name, out_dir, store_uri: seen.append(store_uri) or {"logged": 0}
    )
    before = sorted(tmp_path.rglob("*"))
    ml.main([str(tmp_path), "c", "--uri", "postgresql://lab@db.internal/mlflow"])
    assert seen == ["postgresql://lab@db.internal/mlflow"] and sorted(tmp_path.rglob("*")) == before
    capsys.readouterr()
    monkeypatch.undo()
    monkeypatch.setattr(sys, "argv", ["mlflow_log", str(tmp_path), "c", "--uri", store])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # runpy: the module is already imported by this test
        runpy.run_module("lab.tracking.mlflow_log", run_name="__main__")
    assert json.loads(capsys.readouterr().out)["already_logged"] == 2
