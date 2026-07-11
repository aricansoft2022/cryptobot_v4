"""Conservative net-PnL estimation for exit decisions.

A sell is never triggered by ``current_price > buy_price``. Instead the strategy
computes a conservative estimated net PnL that accounts for:

* the real entry notional and entry fees,
* the actually sellable base quantity,
* estimated market-sell proceeds walked from the live order book (slippage),
* the expected exit commission,
* an extra execution safety buffer.

.. code-block:: text

    estimated_net_pnl =
        estimated_exit_proceeds
        - true_entry_cost
        - entry_fees
        - estimated_exit_fees
        - execution_safety_buffer

Because ``invested_quote_cost = true_entry_cost + entry_fees``, this is
equivalently ``proceeds - exit_fees - buffer - invested_quote_cost``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .orderbook import OrderBook

if TYPE_CHECKING:  # avoid a runtime import cycle (execution <-> strategy)
    from ..strategy.position import StrategyPosition


def _as_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class ExitCostModel:
    """Cost assumptions applied on top of the walked order book.

    Attributes:
        exit_fee_rate: Taker fee rate applied to gross exit proceeds
            (e.g. ``Decimal("0.001")`` for 0.1%).
        safety_buffer_frac: Additional conservative margin as a fraction of gross
            proceeds (e.g. ``Decimal("0.0005")``). Set to ``0`` to disable.
    """

    exit_fee_rate: Decimal = Decimal("0")
    safety_buffer_frac: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if _as_decimal(self.exit_fee_rate) < 0:
            raise ValueError("exit_fee_rate must be >= 0")
        if _as_decimal(self.safety_buffer_frac) < 0:
            raise ValueError("safety_buffer_frac must be >= 0")


@dataclass(frozen=True)
class PnLEstimate:
    """A conservative net-PnL estimate produced for an exit decision."""

    gross_proceeds: Decimal
    filled_qty: Decimal
    fully_filled: bool
    exit_fees: Decimal
    safety_buffer: Decimal
    invested_quote_cost: Decimal
    net_pnl: Decimal

    def meets_target(self, target_net_pnl: Decimal) -> bool:
        """Whether the estimated net PnL reaches ``target_net_pnl`` (inclusive)."""
        return self.net_pnl >= _as_decimal(target_net_pnl)


def estimate_net_pnl(
    position: "StrategyPosition",
    order_book: OrderBook,
    cost_model: ExitCostModel,
) -> PnLEstimate:
    """Estimate the conservative net PnL of exiting ``position`` right now.

    Uses the position's *sellable* base quantity and its real entry cost/fees.
    """
    sellable = _as_decimal(position.entry.sellable_base_qty)
    sell = order_book.estimate_sell_proceeds(sellable)

    exit_fees = sell.gross_proceeds * _as_decimal(cost_model.exit_fee_rate)
    safety_buffer = sell.gross_proceeds * _as_decimal(cost_model.safety_buffer_frac)
    invested = _as_decimal(position.entry.invested_quote_cost)

    net_pnl = sell.gross_proceeds - exit_fees - safety_buffer - invested

    return PnLEstimate(
        gross_proceeds=sell.gross_proceeds,
        filled_qty=sell.filled_qty,
        fully_filled=sell.fully_filled,
        exit_fees=exit_fees,
        safety_buffer=safety_buffer,
        invested_quote_cost=invested,
        net_pnl=net_pnl,
    )
