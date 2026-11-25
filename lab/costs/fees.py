"""The DEX cost model of ``config/costs.yaml`` as a NautilusTrader v2 fee model.

Production trades are swaps on Base through the 0x aggregator. Each swap pays the pool fee, the aggregator fee,
slippage that grows with the trade's size, and gas in USD (sponsored by us, so it is our cost). The rates and the
slippage table are :class:`lab.runner.reference.Costs`, so the reference runner and Nautilus charge the same.

**Slippage is charged as a fee, not as a worse fill price.** ``config/costs.yaml`` gives slippage in bps of the
trade's notional by trade size. Charging it in the commission keeps every fill at the quoted price (the bar's
open) and puts every cost in one number, which the backtest contract reads (``cost``). No fill model is needed:
the runner fills market orders at the top of a book that it sets to the bar's price, with unlimited size.

**Which notional the rates apply to.** By the lab's contract (``lab/runner/interface.py``), a trade's size is
its intended notional: |target weight - drifted weight| x the portfolio's value at the open, and the cost is
taken from the whole book pro rata, so the book holds exactly the target weight after the fill. The order a
runner sends is that trade net of its share of the cost, so its fill notional is slightly smaller. A runner that
follows the contract tags each order with ``intended_usd=<notional>``; the fee is then
``rate(intended) * intended + gas``, which is exactly the reference runner's cost. An untagged order (a paper or
live model account, which sends plain orders) pays the rates on its own fill notional.
"""

from __future__ import annotations

from nautilus_trader.execution import FeeModel
from nautilus_trader.model import Currency, Money

from lab.runner.reference import Costs

INTENDED_TAG = "intended_usd="


def intended_tag(notional_usd: float) -> str:
    """The order tag that carries a trade's intended notional to :class:`DexFeeModel` (exact float repr)."""
    return f"{INTENDED_TAG}{float(notional_usd)!r}"


def fee_usd(costs: Costs, notional_usd: float) -> float:
    """One swap's cost in USD: (pool + aggregator + slippage(notional)) x notional + gas."""
    return costs.rate(notional_usd) * notional_usd + costs.gas_usd_per_trade


class DexFeeModel(FeeModel):
    """Commission of one fill on the Base DEX venue, in ``currency`` (the quote currency of the instrument)."""

    def __init__(self, costs: Costs, currency: Currency) -> None:
        if not isinstance(costs, Costs):
            raise ValueError(f"costs must be a Costs instance, got {type(costs).__name__}")
        self.costs = costs
        self.currency = currency

    def notional(self, order, fill_quantity, fill_px) -> float:
        """The tagged intended notional, else the fill's own notional (quantity x price)."""
        tags = [t for t in (order.tags or []) if t.startswith(INTENDED_TAG)]
        if len(tags) > 1:
            raise ValueError(f"order carries {len(tags)} {INTENDED_TAG} tags, expected at most 1")
        if tags:
            value = float(tags[0][len(INTENDED_TAG) :])
            if not value > 0.0:
                raise ValueError(f"intended notional must be positive, got {value}")
            return value
        return float(fill_quantity) * float(fill_px)

    def get_commission(self, order, fill_quantity, fill_px, instrument) -> Money:
        return Money(fee_usd(self.costs, self.notional(order, fill_quantity, fill_px)), self.currency)
