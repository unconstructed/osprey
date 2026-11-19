"""Pick parameters from a stable region, not a lucky peak.

For each completed trial, average the scores of its k nearest neighbours in
normalized parameter space. The chosen parameters are the trial with the best
neighbourhood average, so small changes to them shouldn't wreck the result.
Equal neighbourhood averages are broken by the trial's own score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .space import Param


def stable_region(trials: pd.DataFrame, specs: list[Param], k: int = 10) -> dict:
    done = trials[(trials["state"] == "COMPLETE") & np.isfinite(trials["value"])].reset_index(drop=True)
    if done.empty:
        raise ValueError("no completed trials")
    units = np.array([[p.to_unit(row[f"params_{p.name}"]) for p in specs] for _, row in done.iterrows()])
    values = done["value"].to_numpy(float)
    k = min(k, len(done))
    dist = np.linalg.norm(units[:, None, :] - units[None, :, :], axis=2)
    neighbours = np.argsort(dist, axis=1)[:, :k]
    # Sorted before averaging, so the same set of scores gives the same mean to the last bit; ties then go to
    # the trial with the best own score instead of to summation-order rounding (e.g. k >= number of trials).
    hood = np.sort(values[neighbours], axis=1).mean(axis=1)
    tied = np.flatnonzero(hood == hood.max())
    i = int(tied[np.argmax(values[tied])])
    j = int(np.argmax(values))
    params_of = lambda r: {p.name: done.loc[r, f"params_{p.name}"] for p in specs}  # noqa: E731
    return {
        "params": params_of(i),
        "trial_number": int(done.loc[i, "number"]),
        "neighbourhood_score": float(hood[i]),
        "own_score": float(values[i]),
        "raw_best_params": params_of(j),
        "raw_best_score": float(values[j]),
    }
