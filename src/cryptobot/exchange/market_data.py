"""Map raw Binance market data into the core's candle and order-book types.

Pure translation only. Signal eligibility (closed / contiguous / same-symbol …)
is enforced downstream by :mod:`cryptobot.market.validation`; here we simply
convert formats and can drop the still-open final kline.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Mapping, Optional, Sequence

from ..execution.orderbook import OrderBook
from ..market.candle import Candle

# Binance REST kline array indices.
_OPEN_TIME = 0
_OPEN = 1
_HIGH = 2
_LOW = 3
_CLOSE = 4
_VOLUME = 5
_CLOSE_TIME = 6


def parse_klines(
    raw: Sequence[Sequence[Any]],
    symbol: str,
    now_ms: Optional[int] = None,
    drop_unclosed: bool = True,
) -> List[Candle]:
    """Convert Binance REST klines into :class:`Candle` objects.

    A kline is considered closed when ``now_ms`` is past its ``closeTime``. When
    ``now_ms`` is ``None`` every kline is treated as closed (historical data).
    With ``drop_unclosed`` set, still-open klines are omitted entirely so only
    signal-eligible candles are returned.
    """
    candles: List[Candle] = []
    for row in raw:
        close_time = int(row[_CLOSE_TIME])
        is_closed = True if now_ms is None else now_ms > close_time
        if not is_closed and drop_unclosed:
            continue
        candles.append(
            Candle(
                symbol=symbol,
                open_time=int(row[_OPEN_TIME]),
                open=float(row[_OPEN]),
                high=float(row[_HIGH]),
                low=float(row[_LOW]),
                close=float(row[_CLOSE]),
                volume=float(row[_VOLUME]),
                is_closed=is_closed,
            )
        )
    return candles


def parse_depth(raw: Mapping[str, Any], symbol: str) -> OrderBook:
    """Convert a Binance depth snapshot (``{bids, asks}``) into an OrderBook.

    ``symbol`` is accepted for symmetry/logging; the order book itself is
    symbol-agnostic.
    """
    bids = [(Decimal(str(p)), Decimal(str(q))) for p, q in raw.get("bids", [])]
    asks = [(Decimal(str(p)), Decimal(str(q))) for p, q in raw.get("asks", [])]
    return OrderBook.from_levels(bids=bids, asks=asks)
