"""A minimal order book used to estimate real market-sell proceeds.

Exit decisions must be based on a conservative estimate of what a market SELL
would actually realize, not on a naive ``current_price > buy_price`` check. That
estimate walks the *bid* side of the book for the sellable quantity, which
naturally captures slippage from limited depth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence, Tuple


@dataclass(frozen=True)
class SellEstimate:
    """Result of walking the bids to sell a target quantity.

    Attributes:
        gross_proceeds: Quote received before fees, for the filled quantity.
        filled_qty: Base quantity that could be filled against the book.
        fully_filled: ``True`` if the whole target quantity was fillable.
    """

    gross_proceeds: Decimal
    filled_qty: Decimal
    fully_filled: bool


def _as_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class OrderBook:
    """A snapshot of best bids (and optionally asks).

    Bids are stored best-first (highest price first). Only the bid side is needed
    to estimate sell proceeds.
    """

    bids: Tuple[Tuple[Decimal, Decimal], ...]
    asks: Tuple[Tuple[Decimal, Decimal], ...] = ()

    @classmethod
    def from_levels(
        cls,
        bids: Iterable[Sequence],
        asks: Iterable[Sequence] = (),
    ) -> "OrderBook":
        """Build an :class:`OrderBook`, coercing prices/quantities to ``Decimal``.

        Bids are sorted best-first defensively.
        """
        norm_bids = tuple(
            sorted(
                ((_as_decimal(p), _as_decimal(q)) for p, q in bids),
                key=lambda level: level[0],
                reverse=True,
            )
        )
        norm_asks = tuple((_as_decimal(p), _as_decimal(q)) for p, q in asks)
        return cls(bids=norm_bids, asks=norm_asks)

    def estimate_sell_proceeds(self, base_qty) -> SellEstimate:
        """Estimate quote proceeds from market-selling ``base_qty`` into the bids.

        Walks bids from best to worst. If the book lacks depth, the estimate
        reflects only the fillable portion (a conservative under-estimate).
        """
        remaining = _as_decimal(base_qty)
        if remaining < 0:
            raise ValueError("base_qty must be >= 0")

        proceeds = Decimal("0")
        for price, available in self.bids:
            if remaining <= 0:
                break
            take = remaining if remaining < available else available
            proceeds += take * price
            remaining -= take

        target = _as_decimal(base_qty)
        filled = target - remaining
        return SellEstimate(
            gross_proceeds=proceeds,
            filled_qty=filled,
            fully_filled=remaining <= 0,
        )
