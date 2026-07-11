"""Open-position model with an immutable strategy snapshot.

When a buy fills, the position captures:

* the exact strategy parameters in force at that moment (immutable snapshot), and
* the real realized entry data (quantity, average price, fees).

Later changes to the coin's settings must not affect an open position: its
snapshot is frozen. The position also owns the normal-exit state machine:
``OPEN -> EXIT_ARMED`` (arming is permanent) ``-> CLOSED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from .parameters import CoinStrategyParameters


class PositionState(str, Enum):
    """Lifecycle state of a position under the normal strategy."""

    OPEN = "OPEN"
    #: RSI has crossed strictly above ``rsi_overbought`` at least once. This is
    #: permanent and is never reverted, even if RSI falls back down.
    EXIT_ARMED = "EXIT_ARMED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class RealizedEntry:
    """Real, realized entry fills — the ground truth for PnL.

    Attributes:
        filled_base_qty: Base quantity actually acquired across all entry fills.
        avg_entry_price: Real average fill price of the entry.
        true_entry_cost: Real quote notional spent (sum of ``price * qty`` fills).
        entry_fees_quote: Entry commissions expressed in quote (USDT) terms.
        sellable_base_qty: Base quantity that can actually be sold later (i.e.
            ``filled_base_qty`` minus any base-denominated commission).
    """

    filled_base_qty: Decimal
    avg_entry_price: Decimal
    true_entry_cost: Decimal
    entry_fees_quote: Decimal
    sellable_base_qty: Decimal

    def __post_init__(self) -> None:
        for name in (
            "filled_base_qty",
            "avg_entry_price",
            "true_entry_cost",
            "entry_fees_quote",
            "sellable_base_qty",
        ):
            if Decimal(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.sellable_base_qty > self.filled_base_qty:
            raise ValueError("sellable_base_qty cannot exceed filled_base_qty")

    @property
    def invested_quote_cost(self) -> Decimal:
        """Total quote committed at entry: notional plus entry fees.

        This is the basis for the minimum-net-profit percentage target.
        """
        return self.true_entry_cost + self.entry_fees_quote


@dataclass
class StrategyPosition:
    """A single open position governed by an immutable strategy snapshot.

    Attributes:
        symbol: The traded symbol.
        snapshot: Frozen strategy parameters captured at open time. All exit
            decisions read from here, never from the coin's live settings.
        entry: The realized entry fills.
        entry_candle_open_time: ``open_time`` of the closed candle that produced
            the entry signal (used for per-candle idempotency).
        state: Current :class:`PositionState`.
        exit_armed_candle_open_time: ``open_time`` of the candle that armed the
            exit, if any.
    """

    symbol: str
    snapshot: CoinStrategyParameters
    entry: RealizedEntry
    entry_candle_open_time: int
    state: PositionState = PositionState.OPEN
    exit_armed_candle_open_time: Optional[int] = field(default=None)

    @property
    def is_exit_armed(self) -> bool:
        return self.state is PositionState.EXIT_ARMED

    def arm_exit(self, candle_open_time: int) -> None:
        """Permanently move the position into ``EXIT_ARMED``.

        Idempotent: re-arming keeps the *original* arming candle. Arming a closed
        position is a programming error.
        """
        if self.state is PositionState.CLOSED:
            raise ValueError("cannot arm exit on a closed position")
        if self.state is PositionState.EXIT_ARMED:
            return
        self.state = PositionState.EXIT_ARMED
        self.exit_armed_candle_open_time = candle_open_time

    def mark_closed(self) -> None:
        self.state = PositionState.CLOSED


def open_position(
    symbol: str,
    params: CoinStrategyParameters,
    entry: RealizedEntry,
    entry_candle_open_time: int,
) -> StrategyPosition:
    """Create a new open position, capturing ``params`` as an immutable snapshot.

    ``CoinStrategyParameters`` is already frozen, so the snapshot cannot be
    mutated; storing the instance directly is sufficient to guarantee the
    position never observes later setting changes.
    """
    return StrategyPosition(
        symbol=symbol,
        snapshot=params,
        entry=entry,
        entry_candle_open_time=entry_candle_open_time,
    )
