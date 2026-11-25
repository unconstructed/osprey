"""Every search trial as an MLflow run (AGENTS.md "Running many simulations", rule 4).

The Optuna journal and the Parquet files ``lab.search.study`` writes stay the record that DSR and PBO read. This
module copies a study into MLflow afterwards, so every trial can be browsed (``uv run mlflow ui``): one parent run
per study, holding the search config, and one child run per finished trial (complete, failed or pruned), with

- **params**: the trial's parameters;
- **metrics**: the score (``value``), Sharpe, trade count and each block's Sharpe, where the trial has them;
- **tags**: study, trial number, state, strategy, window, data snapshot id, git commit and seed. The snapshot, the
  commit and the strategy come from the ``context`` the caller passed to ``run_study``; one not recorded there is
  tagged ``unrecorded``, never guessed.

It reads the study after it ran, from its journal, so parallel workers never write to MLflow at the same time, and a
failed trial is logged as a FAILED run. Logging again (after a resumed study, or twice) adds only trials not yet
logged; a trial still running is left for the next call.

    uv run python -m lab.tracking.mlflow_log <results dir> <study name> [--uri sqlite:///mlruns/mlflow.db]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import optuna
import pandas as pd
from mlflow.entities import Metric, Param, RunTag
from mlflow.tracking import MlflowClient

from lab.search.study import SearchConfig, _storage, run_study

DEFAULT_URI = "sqlite:///mlruns/mlflow.db"
UNRECORDED = "unrecorded"
FINISHED = {
    optuna.trial.TrialState.COMPLETE: "FINISHED",
    optuna.trial.TrialState.FAIL: "FAILED",
    optuna.trial.TrialState.PRUNED: "KILLED",
}
_CONTEXT_TAGS = ("strategy", "snapshot_id", "git_commit")
PAGE = 1000  # runs per search page


def _study_tags(name: str, meta: dict) -> dict[str, str]:
    tags = {"osprey.study": name, "osprey.window": " .. ".join(map(str, meta.get("window", [UNRECORDED])))}
    tags["osprey.seed"] = str(meta.get("config", {}).get("seed", UNRECORDED))
    for key in _CONTEXT_TAGS:
        tags[f"osprey.{key}"] = str(meta.get(key, UNRECORDED))
    return tags


def _runs(client: MlflowClient, experiment_id: str, name: str) -> list:
    runs, token = [], None
    while True:
        page = client.search_runs(
            [experiment_id],
            filter_string=f"tags.`osprey.study` = '{name}'",
            max_results=PAGE,
            page_token=token,
        )
        runs.extend(page)
        token = page.token
        if not token:
            return runs


def _metrics(trial: optuna.trial.FrozenTrial, ts: int) -> list[Metric]:
    values = {
        "value": trial.value,
        "sharpe": trial.user_attrs.get("sharpe"),
        "n_trades": trial.user_attrs.get("n_trades"),
    }
    for i, s in enumerate(trial.user_attrs.get("block_sharpes", [])):
        values[f"block_sharpe_{i}"] = s
    return [
        Metric(k, float(v), ts, 0) for k, v in values.items() if v is not None and math.isfinite(float(v))
    ]


def log_study(
    name: str, out_dir: str | Path, tracking_uri: str = DEFAULT_URI, experiment: str | None = None
) -> dict:
    """Log study ``name`` (in ``out_dir/name``) to MLflow; returns counts of what was logged and skipped."""
    folder = Path(out_dir) / name
    if not (folder / "study.journal").is_file():
        raise FileNotFoundError(f"{folder / 'study.journal'} not found: run the study first")
    meta = json.loads((folder / "meta.json").read_text())
    study = optuna.load_study(study_name=name, storage=_storage(folder / "study.journal"))
    client = MlflowClient(tracking_uri)
    exp = client.get_experiment_by_name(experiment or name)
    experiment_id = exp.experiment_id if exp else client.create_experiment(experiment or name)
    tags = _study_tags(name, meta)
    runs = _runs(client, experiment_id, name)
    parents = [r for r in runs if r.data.tags.get("osprey.kind") == "study"]
    if parents:
        parent_id = parents[0].info.run_id
    else:
        parent = client.create_run(experiment_id, tags={**tags, "osprey.kind": "study"}, run_name=name)
        parent_id = parent.info.run_id
        config = {f"config_{k}": v for k, v in meta.get("config", {}).items()}
        client.log_batch(parent_id, params=[Param(k, str(v)) for k, v in config.items()])
        client.set_terminated(parent_id, "FINISHED")
    logged = {r.data.tags.get("osprey.trial") for r in runs if r.data.tags.get("osprey.kind") == "trial"}
    counts = {"logged": 0, "already_logged": 0, "unfinished": 0}
    for trial in study.trials:
        if trial.state not in FINISHED:
            counts["unfinished"] += 1
            continue
        if str(trial.number) in logged:
            counts["already_logged"] += 1
            continue
        run_tags = {
            **tags,
            "osprey.kind": "trial",
            "osprey.trial": str(trial.number),
            "osprey.state": trial.state.name,
            "mlflow.parentRunId": parent_id,
        }
        run = client.create_run(experiment_id, tags=run_tags, run_name=f"{name}/t{trial.number}")
        ts = int(pd.Timestamp(trial.datetime_complete or trial.datetime_start or 0).timestamp() * 1000)
        client.log_batch(
            run.info.run_id,
            metrics=_metrics(trial, ts),
            params=[Param(k, str(v)) for k, v in trial.params.items()],
            tags=[RunTag("osprey.trial_state", trial.state.name)],
        )
        client.set_terminated(run.info.run_id, FINISHED[trial.state])
        counts["logged"] += 1
    return {**counts, "experiment_id": experiment_id, "parent_run_id": parent_id}


def run_and_log(
    name,
    backtest_fn,
    specs,
    bars,
    out_dir,
    cfg: SearchConfig | None = None,
    context=None,
    tracking_uri=DEFAULT_URI,
) -> pd.DataFrame:
    """``lab.search.study.run_study`` followed by :func:`log_study`: the trials table, every trial in MLflow."""
    trials = run_study(name, backtest_fn, specs, bars, out_dir, cfg or SearchConfig(), context)
    log_study(name, out_dir, tracking_uri)
    return trials


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Log a finished search study to MLflow.")
    parser.add_argument("out_dir")
    parser.add_argument("name")
    parser.add_argument("--uri", default=DEFAULT_URI)
    args = parser.parse_args(argv)
    if args.uri.startswith("sqlite:///"):
        Path(args.uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    counts = log_study(args.name, args.out_dir, args.uri)
    print(json.dumps(counts))
    return counts


if __name__ == "__main__":
    main()
