"""Search-space definitions shared by Optuna studies and the stable-region finder."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Param:
    name: str
    kind: str                      # "int", "float" or "cat"
    low: float | None = None
    high: float | None = None
    log: bool = False
    choices: tuple = field(default_factory=tuple)

    def suggest(self, trial):
        if self.kind == "int":
            return trial.suggest_int(self.name, int(self.low), int(self.high), log=self.log)
        if self.kind == "float":
            return trial.suggest_float(self.name, self.low, self.high, log=self.log)
        if self.kind == "cat":
            return trial.suggest_categorical(self.name, list(self.choices))
        raise ValueError(self.kind)

    def to_unit(self, value) -> float:
        """Map a value to [0, 1] so distances between trials are comparable."""
        if self.kind == "cat":
            return self.choices.index(value) / max(1, len(self.choices) - 1)
        lo, hi, v = float(self.low), float(self.high), float(value)
        if self.log:
            lo, hi, v = np.log(lo), np.log(hi), np.log(v)
        return (v - lo) / (hi - lo) if hi > lo else 0.0


def suggest_all(trial, specs: list[Param]) -> dict:
    return {p.name: p.suggest(trial) for p in specs}


def from_dict(spec: dict) -> list[Param]:
    """Build from params.yaml style: {name: {kind, low, high, log, choices}}."""
    return [Param(name=k, **v) for k, v in spec.items()]
