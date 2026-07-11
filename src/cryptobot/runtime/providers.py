"""Concrete operational providers and helpers.

These are *operational* utilities, not strategy rules: a wall-clock source, a
default order-sizing helper, and a market-data freshness check. They are plain,
overridable functions/classes the caller may use or replace. None of them alters
the deterministic entry/exit signal.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Sequence

from ..market.candle import INTERVAL_MS, Candle
from ..strategy.parameters import CoinStrategyParameters


class SystemClock:
    """A ``ClockPort`` using the system wall clock (epoch milliseconds)."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def equal_slot_quote_amount(
    params: CoinStrategyParameters,
    open_and_reserved_slots: int,
    used_capital_usdt: Any,
) -> Decimal:
    """Default per-order size: an equal share of the coin's capital per slot.

    Operational only. Returns ``capital_limit_usdt / slot_count`` capped by the
    coin's remaining capital headroom, or ``0`` when no slot/capital is free.
    Callers may substitute any other sizing policy.
    """
    if open_and_reserved_slots >= params.slot_count:
        return Decimal("0")
    remaining_capital = params.capital_limit_usdt - _as_decimal(used_capital_usdt)
    if remaining_capital <= 0:
        return Decimal("0")
    per_slot = params.capital_limit_usdt / params.slot_count
    return per_slot if per_slot <= remaining_capital else remaining_capital


def is_market_data_fresh(
    candles: Sequence[Candle],
    now_ms: int,
    max_lag_ms: int = 2 * INTERVAL_MS,
) -> bool:
    """Whether the latest closed candle is recent enough to act on.

    Operational helper for the ``market_data_fresh`` gate: the most recent
    candle's close time must be within ``max_lag_ms`` of ``now_ms``.
    """
    if not candles:
        return False
    last_close_time = candles[-1].open_time + INTERVAL_MS - 1
    return 0 <= (now_ms - last_close_time) <= max_lag_ms
