"""Replay ports that feed a historical candle series to the live service.

``ReplayMarketData`` exposes candles only up to the current replay index (so the
engine never sees the future) and synthesizes an order book from the current
candle's close with a configurable spread — enough for the exact same exit /
PnL code path to run. ``BacktestClock`` tracks simulated time so the
``market_data_fresh`` gate behaves as it would live.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Sequence

from ..execution.orderbook import OrderBook
from ..market.candle import INTERVAL_MS, Candle

# A depth large enough that simulated market orders always fill fully.
_DEPTH = Decimal("1_000_000_000_000")


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class BacktestClock:
    """A ``ClockPort`` whose time is set from the current replay candle."""

    def __init__(self) -> None:
        self._now_ms = 0

    def advance_to(self, candle: Candle) -> None:
        # Just after the candle closes, mirroring how a live tick would fire.
        self._now_ms = candle.open_time + INTERVAL_MS

    def now_ms(self) -> int:
        return self._now_ms


class ReplayMarketData:
    """A ``MarketDataPort`` that replays a fixed history up to a moving index.

    Args:
        series: Full historical candles per symbol (chronological, contiguous).
        spread_frac: Half-spread applied to synthesize bid/ask around the close
            (e.g. ``Decimal("0.0005")`` for 5 bps each side). Models slippage.
    """

    def __init__(
        self,
        series: Mapping[str, Sequence[Candle]],
        spread_frac: Any = Decimal("0"),
    ) -> None:
        self._series: Dict[str, List[Candle]] = {s: list(c) for s, c in series.items()}
        self._spread = _as_decimal(spread_frac)
        self._index: Dict[str, int] = {s: -1 for s in self._series}

    def set_index(self, symbol: str, index: int) -> None:
        self._index[symbol] = index

    def current_candle(self, symbol: str) -> Candle:
        return self._series[symbol][self._index[symbol]]

    def get_closed_candles(self, symbol: str, limit: int) -> List[Candle]:
        index = self._index.get(symbol, -1)
        if index < 0:
            return []
        window = self._series[symbol][: index + 1]
        return window[-limit:] if limit else window

    def get_order_book(self, symbol: str) -> OrderBook:
        index = self._index.get(symbol, -1)
        if index < 0:
            return OrderBook(bids=(), asks=())
        price = _as_decimal(self._series[symbol][index].close)
        bid = price * (Decimal("1") - self._spread)
        ask = price * (Decimal("1") + self._spread)
        return OrderBook.from_levels(bids=[(bid, _DEPTH)], asks=[(ask, _DEPTH)])
