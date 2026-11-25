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

import numpy as np
import pandas as pd
import pytest

from lab.runner import nautilus, reference
from lab.runner.interface import validate_bars
from lab.runner.reference import Costs


def dip_buy_with_forecast(params: dict, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """``dip_buy`` sized from a model column (``vol_col``). The stand-in forecast is a point-in-time function of
    the bars: 1.2 x the annualised 5-bar realised volatility, NaN for the first 5 bars (so the fallback to
    realised volatility runs too). Tampering bars from ``cut`` on therefore can't move it before ``cut``."""
    validate_bars(bars)
    forecast = 1.2 * reference.realised_vol(bars["close"].to_numpy(dtype=float), 5)
    return reference.dip_buy({**params, "vol_col": "pred_vol"}, bars.assign(pred_vol=forecast), costs)


def scheduled_ladder(params: dict, bars: pd.DataFrame, costs: Costs | None = None) -> pd.DataFrame:
    """``scheduled`` on a point-in-time ladder column ``target``: at close t, the share of the last 3 bars that
    closed down (0, 1/3, 2/3 or 1; 0 before 3 returns exist). Partial steps up and down exercise drifted weights
    inside one round trip. The column at t reads closes t-3..t only, so tampering bars from ``cut`` on can't move
    it before ``cut``. ``params`` pass through unchanged (``{"col": "target"}``)."""
    validate_bars(bars)
    close = bars["close"].to_numpy(dtype=float)
    down = np.zeros(len(close))
    down[1:] = close[1:] < close[:-1]
    ladder = np.zeros(len(close))
    for t in range(3, len(close)):
        ladder[t] = down[t - 2 : t + 1].sum() / 3.0
    return reference.scheduled(params, bars.assign(target=ladder), costs)


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
        {
            "drop": 0.04,
            "lookback": 5,
            "stop": 0.03,
            "hold": 4,
            "weight": 0.8,
            "vol_target": 0.5,
            "vol_lookback": 5,
        },
        bad_params=(
            {"drop": 0.04, "lookback": 5, "stop": 1.0},
            {"drop": 0.04, "lookback": 5, "hold": 0},
            {"drop": 0.04, "lookback": 5, "vol_target": -0.5},
            {"drop": 0.04, "lookback": 5, "vol_target": 0.5, "vol_lookback": 1},
        ),
    ),
    Runner(
        "ref_dip_buy_model_vol",
        dip_buy_with_forecast,
        {"drop": 0.05, "lookback": 5, "hold": 6, "vol_target": 0.5},
        bad_params=({"drop": 0.05, "lookback": 5}, {"drop": 0.05, "lookback": 5, "vol_target": 0.0}),
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
        "ref_scheduled_ladder",
        scheduled_ladder,
        {"col": "target"},
        bad_params=({}, {"col": "nope"}, {"col": "close"}, {"col": "volume"}, {"col": "target", "hold": 3}),
    ),
    Runner(
        "ref_random_entry",
        reference.random_entry,
        {"n_trades": 3, "hold": 3, "seed": 7},
        bad_params=({"n_trades": 3}, {"n_trades": -1, "hold": 3}, {"n_trades": 50, "hold": 30}),
    ),
)


REFERENCE_RUNNERS = RUNNERS

# Milestone 2: every reference entry again, on NautilusTrader (lab/runner/nautilus.py). Same rule code, same
# params and bad params; the book, the orders, the fills and the fees are Nautilus's. Its tolerance is the
# runner's written-down fixed-point round-off (nautilus.TOL).
NAUTILUS_RUNNERS = tuple(
    Runner(
        r.name.replace("ref_", "nautilus_", 1),
        nautilus.wrap(r.fn),
        r.params,
        supports_costs=r.supports_costs,
        tol=nautilus.TOL,
        bad_params=r.bad_params,
    )
    for r in REFERENCE_RUNNERS
)

RUNNERS = REFERENCE_RUNNERS + NAUTILUS_RUNNERS


@pytest.fixture(scope="session", params=RUNNERS, ids=[r.name for r in RUNNERS])
def runner(request) -> Runner:
    return request.param
