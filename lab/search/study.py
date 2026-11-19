"""Optuna studies: Bayesian (TPE) search, run in parallel processes, every trial logged.

Storage is an Optuna journal file, so several processes on one machine share the study
safely and a crashed run can resume. For many machines, swap in RDBStorage (Postgres).

Every trial writes its full return series to results/<study>/returns/ so the auditor
can compute the Deflated Sharpe Ratio (with the effective trial count) and the
Probability of Backtest Overfitting across everything that was tried.

Reproducibility: with n_workers > 1, Optuna's search order depends on process timing,
so two runs can pick different parameters. Every trial is logged, and re-running any
logged parameter set is exact. Treat a big difference between two searches with
different seeds as a fragility warning about the strategy.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

from ..runner.interface import BacktestFn
from .objective import evaluate_params
from .space import Param, suggest_all

optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class SearchConfig:
    n_trials: int = 200
    n_workers: int = 4
    n_blocks: int = 4
    penalty: float = 0.5
    seed: int = 0
    periods_per_year: int = 365
    min_trades: int = 5


def _storage(path: Path):
    from optuna.storages import JournalStorage
    from optuna.storages.journal import JournalFileBackend

    return JournalStorage(JournalFileBackend(str(path)))


def _worker(args) -> None:
    name, out_dir, backtest_fn, specs, bars, cfg_dict, worker_id, n_trials = args
    cfg = SearchConfig(**cfg_dict)
    out = Path(out_dir) / name
    sampler = optuna.samplers.TPESampler(
        seed=cfg.seed + worker_id, multivariate=True, n_startup_trials=min(20, max(5, n_trials // 4))
    )
    study = optuna.load_study(study_name=name, storage=_storage(out / "study.journal"), sampler=sampler)

    def objective(trial: optuna.Trial) -> float:
        params = suggest_all(trial, specs)
        res = evaluate_params(
            backtest_fn, params, bars, cfg.n_blocks, cfg.penalty, cfg.periods_per_year, cfg.min_trades
        )
        trial.set_user_attr("block_sharpes", res["block_sharpes"])
        trial.set_user_attr("sharpe", res["sharpe"])
        trial.set_user_attr("n_trades", res["n_trades"])
        res["returns"].rename(f"t{trial.number}").to_frame().to_parquet(
            out / "returns" / f"trial_{trial.number:06d}.parquet"
        )
        return res["score"]

    study.optimize(objective, n_trials=n_trials, catch=(Exception,))


def run_study(
    name: str,
    backtest_fn: BacktestFn,
    specs: list[Param],
    bars: pd.DataFrame,
    out_dir: str | Path,
    cfg: SearchConfig = SearchConfig(),  # noqa: B008 - never mutated (callers use dataclasses.replace)
    context: dict | None = None,
) -> pd.DataFrame:
    """Run (or resume) a study; returns one row per trial, including failed ones."""
    out = Path(out_dir) / name
    (out / "returns").mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name=name, storage=_storage(out / "study.journal"), direction="maximize", load_if_exists=True
    )
    meta = {"config": asdict(cfg), "window": [str(bars.index[0]), str(bars.index[-1])], **(context or {})}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    for k, v in meta.items():
        study.set_user_attr(k, v)

    workers = max(1, cfg.n_workers)
    per_worker = [cfg.n_trials // workers + (1 if i < cfg.n_trials % workers else 0) for i in range(workers)]
    jobs = [(name, str(out_dir), backtest_fn, specs, bars, asdict(cfg), i, k) for i, k in enumerate(per_worker) if k]
    if workers == 1:
        for j in jobs:
            _worker(j)
    else:
        with mp.get_context("spawn").Pool(len(jobs)) as pool:
            pool.map(_worker, jobs)

    return load_trials(name, out_dir)


def load_trials(name: str, out_dir: str | Path) -> pd.DataFrame:
    out = Path(out_dir) / name
    study = optuna.load_study(study_name=name, storage=_storage(out / "study.journal"))
    rows = []
    for t in study.trials:
        rows.append(
            {
                "number": t.number,
                "state": t.state.name,
                "value": t.value if t.value is not None else np.nan,
                **{f"params_{k}": v for k, v in t.params.items()},
                "sharpe": t.user_attrs.get("sharpe", np.nan),
                "n_trades": t.user_attrs.get("n_trades", 0),
            }
        )
    df = pd.DataFrame(rows).sort_values("number").reset_index(drop=True)
    df.to_parquet(out / "trials.parquet")
    return df


def load_trial_returns(name: str, out_dir: str | Path) -> pd.DataFrame:
    """(periods x trials) matrix of every completed trial's returns.

    Only trials Optuna recorded as COMPLETE count. A worker killed after writing its
    returns file but before the result was stored leaves an orphan file; counting it
    would add a phantom trial to the DSR and PBO.
    """
    out = Path(out_dir) / name
    study = optuna.load_study(study_name=name, storage=_storage(out / "study.journal"))
    done = [t.number for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    files = [out / "returns" / f"trial_{n:06d}.parquet" for n in done]
    files = [f for f in files if f.exists()]
    return pd.concat([pd.read_parquet(f) for f in files], axis=1) if files else pd.DataFrame()
