"""Aggregate real Binance fills into realized entry data and realized PnL.

The pre-trade net-PnL estimate drives the decision; the *realized* result must be
computed solely from real Binance fills and commissions. This module converts a
list of fills into an immutable :class:`~cryptobot.strategy.position.RealizedEntry`
and computes realized PnL from real sell fills, plus the estimate-vs-realized
slippage used for audit/reporting.

Commission handling:

* commission in the quote asset -> added to the quote-denominated fee total;
* commission in the base asset  -> reduces the sellable base quantity and is
  valued into the fee total at the average fill price;
* commission in any other asset (e.g. BNB) -> converted to quote via an injected
  ``commission_rates`` map (asset -> quote price); missing rate is an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence

from ..strategy.position import RealizedEntry


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class Fill:
    """A single execution fill (mirrors Binance order ``fills`` entries)."""

    price: Decimal
    qty: Decimal
    commission: Decimal = Decimal("0")
    commission_asset: str = ""

    @classmethod
    def from_binance(cls, raw: Mapping[str, Any]) -> "Fill":
        return cls(
            price=_as_decimal(raw["price"]),
            qty=_as_decimal(raw["qty"]),
            commission=_as_decimal(raw.get("commission", "0")),
            commission_asset=str(raw.get("commissionAsset", "")),
        )


def _commission_in_quote(
    fill: Fill,
    base_asset: str,
    quote_asset: str,
    avg_price: Decimal,
    commission_rates: Optional[Mapping[str, Any]],
) -> Decimal:
    """Value a fill's commission in quote terms (base commission uses avg price)."""
    if fill.commission == 0:
        return Decimal("0")
    asset = fill.commission_asset
    if asset == quote_asset:
        return fill.commission
    if asset == base_asset:
        return fill.commission * avg_price
    if commission_rates and asset in commission_rates:
        return fill.commission * _as_decimal(commission_rates[asset])
    raise ValueError(
        f"cannot value commission in {asset!r}: provide commission_rates[{asset!r}]"
    )


def aggregate_entry(
    fills: Sequence[Fill],
    base_asset: str,
    quote_asset: str,
    commission_rates: Optional[Mapping[str, Any]] = None,
) -> RealizedEntry:
    """Build a :class:`RealizedEntry` from real entry (buy) fills."""
    if not fills:
        raise ValueError("cannot aggregate an empty fill list")

    filled_base = sum((f.qty for f in fills), Decimal("0"))
    true_cost = sum((f.price * f.qty for f in fills), Decimal("0"))
    if filled_base <= 0:
        raise ValueError("aggregated base quantity must be positive")
    avg_price = true_cost / filled_base

    fees_quote = Decimal("0")
    base_commission = Decimal("0")
    for fill in fills:
        fees_quote += _commission_in_quote(
            fill, base_asset, quote_asset, avg_price, commission_rates
        )
        if fill.commission_asset == base_asset:
            base_commission += fill.commission

    sellable = filled_base - base_commission
    return RealizedEntry(
        filled_base_qty=filled_base,
        avg_entry_price=avg_price,
        true_entry_cost=true_cost,
        entry_fees_quote=fees_quote,
        sellable_base_qty=sellable,
    )


@dataclass(frozen=True)
class RealizedPnL:
    """Realized PnL of a completed round trip, from real fills only."""

    gross_proceeds: Decimal
    exit_fees_quote: Decimal
    exit_qty: Decimal
    invested_quote_cost: Decimal
    net_pnl: Decimal

    def slippage_vs_estimate(self, estimated_net_pnl: Any) -> Decimal:
        """Realized minus estimated net PnL (negative == worse than estimate)."""
        return self.net_pnl - _as_decimal(estimated_net_pnl)


def realized_pnl(
    entry: RealizedEntry,
    sell_fills: Sequence[Fill],
    base_asset: str,
    quote_asset: str,
    commission_rates: Optional[Mapping[str, Any]] = None,
) -> RealizedPnL:
    """Compute realized PnL from real sell fills against a position's entry."""
    if not sell_fills:
        raise ValueError("cannot compute realized PnL with no sell fills")

    gross = sum((f.price * f.qty for f in sell_fills), Decimal("0"))
    exit_qty = sum((f.qty for f in sell_fills), Decimal("0"))
    avg_exit = gross / exit_qty if exit_qty > 0 else Decimal("0")

    exit_fees = Decimal("0")
    for fill in sell_fills:
        exit_fees += _commission_in_quote(
            fill, base_asset, quote_asset, avg_exit, commission_rates
        )

    invested = entry.invested_quote_cost
    net = gross - exit_fees - invested
    return RealizedPnL(
        gross_proceeds=gross,
        exit_fees_quote=exit_fees,
        exit_qty=exit_qty,
        invested_quote_cost=invested,
        net_pnl=net,
    )
