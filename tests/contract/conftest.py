"""Runners under the backtest contract (TESTING.md 5.6).

Every test in ``tests/contract/`` takes the parametrised ``runner`` fixture, so each guarantee runs against
every entry of ``RUNNERS``. **Adding a runner is one new entry**, e.g. for milestone 2:

    Runner("nautilus_dip_buy", nautilus.dip_buy, {"drop": 0.05, "lookback": 5}, tol=1e-8,
           bad_params=({"drop": 0.0, "lookback": 5},))

Choose ``params`` that trade often on ordinary random paths (``test_runner_trades_on_the_synthetic_market``
guards against a vacuous entry). ``tol`` is the absolute tolerance of the per-bar identities: round-off only
for the reference (1e-12). An engine that keeps cash and coin quantities in fixed precision gets a looser,
written-down value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
import pytest

from lab.runner import reference
from lab.runner.reference import Costs


@dataclass(frozen=True)
class Runner:
    """One runner with one parameter set, as the contract tests see it.

    - ``fn(params, bars)`` or, if ``supports_costs``, ``fn(params, bars, costs=Costs)``.
    - ``params``: passed as is (not copied), so a runner that mutates its params is caught.
    - ``tol``: absolute tolerance for the per-bar identities (scaled by the bar count for products).
    - ``bad_params``: parameter sets the runner must reject with ``ValueError``.
    """

    name: str
    fn: Callable[..., pd.DataFrame]
    params: dict
    supports_costs: bool = True
    tol: float = 1e-12
    bad_params: tuple[dict, ...] = field(default=())

    def run(self, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
        """Run on ``bars``. ``costs=None`` uses the runner's own default (config/costs.yaml)."""
        if costs is None:
            return self.fn(self.params, bars)
        if not self.supports_costs:
            pytest.skip(f"{self.name} does not take a cost model")
        return self.fn(self.params, bars, costs=costs)


RUNNERS: tuple[Runner, ...] = (
    Runner(
        "ref_dip_buy",
        reference.dip_buy,
        {"drop": 0.05, "lookback": 5},
        bad_params=(
            {},
            {"drop": 0.0, "lookback": 5},
            {"drop": 0.05, "lookback": 0},
            {"drop": 0.05, "lookback": 5, "stop_loss": 0.1},
        ),
    ),
    Runner(
        "ref_dip_buy_stop_hold_vol",
        reference.dip_buy,
        {"drop": 0.04, "lookback": 5, "stop": 0.03, "hold": 4, "weight": 0.8, "vol_target": 0.5, "vol_lookback": 5},
        bad_params=(
            {"drop": 0.04, "lookback": 5, "stop": 1.0},
            {"drop": 0.04, "lookback": 5, "hold": 0},
            {"drop": 0.04, "lookback": 5, "vol_target": -0.5},
            {"drop": 0.04, "lookback": 5, "vol_target": 0.5, "vol_lookback": 1},
        ),
    ),
    Runner("ref_buy_and_hold", reference.buy_and_hold, {}, bad_params=({"weight": 0.0}, {"weight": 1.5})),
    Runner("ref_buy_and_hold_half", reference.buy_and_hold, {"weight": 0.5}, bad_params=({"size": 0.5},)),
    Runner(
        "ref_constant_mix",
        reference.constant_mix,
        {"weight": 0.5},
        bad_params=({"weight": 1.2}, {"every": 0}, {"band": -0.1}),
    ),
    Runner(
        "ref_constant_mix_every_band",
        reference.constant_mix,
        {"weight": 0.6, "every": 3, "band": 0.01},
        bad_params=({"band": 1.0}, {"every": 2.5}),
    ),
    Runner(
        "ref_random_entry",
        reference.random_entry,
        {"n_trades": 3, "hold": 3, "seed": 7},
        bad_params=({"n_trades": 3}, {"n_trades": -1, "hold": 3}, {"n_trades": 50, "hold": 30}),
    ),
)


@pytest.fixture(scope="session", params=RUNNERS, ids=[r.name for r in RUNNERS])
def runner(request) -> Runner:
    return request.param
