"""Injected dependencies (ports) the trading runtime depends on.

These structural ``Protocol`` interfaces decouple the deterministic decision core
from live infrastructure. A real deployment supplies Binance-backed
implementations; tests supply in-memory fakes. No implementation here performs
I/O — that is entirely the adapter's concern.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Protocol, runtime_checkable

from ..execution.orderbook import OrderBook
from ..exchange.fills import Fill
from ..market.candle import Candle


@runtime_checkable
class MarketDataPort(Protocol):
    """Source of closed candles and order-book snapshots."""

    def get_closed_candles(self, symbol: str, limit: int) -> List[Candle]:
        ...

    def get_order_book(self, symbol: str) -> OrderBook:
        ...


@runtime_checkable
class AccountPort(Protocol):
    """Account state used by the operational gates and sizing."""

    def available_quote_balance(self) -> Decimal:
        ...

    def used_capital(self, symbol: str) -> Decimal:
        ...

    def open_and_reserved_slots(self, symbol: str) -> int:
        ...


@runtime_checkable
class ExecutionPort(Protocol):
    """Places market orders and returns the resulting real fills."""

    def market_buy(self, symbol: str, quote_amount: Decimal) -> List[Fill]:
        ...

    def market_sell(self, symbol: str, base_qty: Decimal) -> List[Fill]:
        ...


@runtime_checkable
class ClockPort(Protocol):
    """Monotonic wall-clock source in epoch milliseconds."""

    def now_ms(self) -> int:
        ...
