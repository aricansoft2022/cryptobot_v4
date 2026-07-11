"""Binance symbol filters — order acceptance and increment rounding.

The ``symbol_filters_ok`` operational gate requires that an order's size and
notional are acceptable to Binance. This module parses the relevant filters from
``exchangeInfo`` and provides deterministic rounding + validation:

* ``LOT_SIZE`` / ``MARKET_LOT_SIZE`` — ``minQty``, ``maxQty``, ``stepSize``
* ``PRICE_FILTER`` — ``minPrice``, ``maxPrice``, ``tickSize``
* ``NOTIONAL`` / ``MIN_NOTIONAL`` — ``minNotional``

This is pure exchange mechanics; it makes no strategy decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Mapping, Sequence


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Floor ``value`` to the nearest lower multiple of ``increment``."""
    if increment <= 0:
        return value
    steps = (value / increment).to_integral_value(rounding=ROUND_DOWN)
    result = steps * increment
    # Normalize to the increment's exponent to avoid trailing precision noise.
    return result.quantize(increment) if increment.as_tuple().exponent < 0 else result


@dataclass(frozen=True)
class SymbolFilters:
    """Parsed, validated Binance order filters for a single symbol."""

    symbol: str
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    tick_size: Decimal
    min_price: Decimal
    max_price: Decimal
    min_notional: Decimal

    def round_quantity(self, qty: Any) -> Decimal:
        """Floor ``qty`` to a valid ``stepSize`` multiple."""
        return _floor_to_increment(_as_decimal(qty), self.step_size)

    def round_price(self, price: Any) -> Decimal:
        """Floor ``price`` to a valid ``tickSize`` multiple."""
        return _floor_to_increment(_as_decimal(price), self.tick_size)

    def quantity_ok(self, qty: Any) -> bool:
        """Whether ``qty`` is within ``[minQty, maxQty]`` and on the step grid."""
        q = _as_decimal(qty)
        if q < self.min_qty or q > self.max_qty:
            return False
        if self.step_size > 0 and _floor_to_increment(q, self.step_size) != q:
            return False
        return True

    def notional_ok(self, price: Any, qty: Any) -> bool:
        """Whether ``price * qty`` meets ``minNotional``."""
        return _as_decimal(price) * _as_decimal(qty) >= self.min_notional

    def accepts_order(self, price: Any, qty: Any) -> bool:
        """Whether an order of ``qty`` at ``price`` passes every filter."""
        return self.quantity_ok(qty) and self.notional_ok(price, qty)

    @classmethod
    def from_exchange_info_symbol(cls, info: Mapping[str, Any]) -> "SymbolFilters":
        """Build from one entry of Binance ``exchangeInfo['symbols']``.

        Prefers ``MARKET_LOT_SIZE`` over ``LOT_SIZE`` when present (market orders
        use the market lot size). Accepts either ``NOTIONAL`` or the legacy
        ``MIN_NOTIONAL`` filter.
        """
        filters: Sequence[Mapping[str, Any]] = info.get("filters", [])
        by_type = {f.get("filterType"): f for f in filters}

        lot = by_type.get("MARKET_LOT_SIZE") or by_type.get("LOT_SIZE")
        if lot is None:
            raise ValueError(f"symbol {info.get('symbol')!r} has no LOT_SIZE filter")
        price = by_type.get("PRICE_FILTER", {})
        notional = by_type.get("NOTIONAL") or by_type.get("MIN_NOTIONAL") or {}

        return cls(
            symbol=str(info.get("symbol")),
            step_size=_as_decimal(lot["stepSize"]),
            min_qty=_as_decimal(lot["minQty"]),
            max_qty=_as_decimal(lot["maxQty"]),
            tick_size=_as_decimal(price.get("tickSize", "0")),
            min_price=_as_decimal(price.get("minPrice", "0")),
            max_price=_as_decimal(price.get("maxPrice", "0")),
            min_notional=_as_decimal(notional.get("minNotional", "0")),
        )
