"""Binance WebSocket streaming market data implementing ``MarketDataPort``.

Follows the same injected-source pattern as the REST client: this component folds
already-parsed WebSocket JSON messages into in-memory state (a rolling buffer of
closed candles and the latest order book per symbol). The actual socket loop lives
outside — production feeds messages in via :meth:`process_message`; tests feed
them directly.

Only **closed** kline messages (``k.x == true``) update the candle buffer. The
buffer replaces a same-``open_time`` candle and ignores stale (older) ones;
contiguity/gap enforcement stays downstream in
:mod:`cryptobot.market.validation`, preserving the fail-closed guarantee.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence

from ..execution.orderbook import OrderBook
from ..market.candle import Candle


def _kline_to_candle(symbol: str, k: Mapping[str, Any]) -> Candle:
    return Candle(
        symbol=symbol,
        open_time=int(k["t"]),
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        is_closed=bool(k.get("x", False)),
    )


def _stream_symbol(stream: str) -> str:
    """Extract the upper-case symbol from a combined-stream name like
    ``"btcusdt@depth20@100ms"``."""
    return stream.split("@", 1)[0].upper()


class StreamingMarketData:
    """A ``MarketDataPort`` fed by Binance WebSocket messages.

    Args:
        max_candles: Rolling buffer size per symbol.
    """

    def __init__(self, max_candles: int = 1000) -> None:
        self._max_candles = max_candles
        self._candles: Dict[str, Deque[Candle]] = {}
        self._books: Dict[str, OrderBook] = {}

    # -- priming ------------------------------------------------------------

    def seed_candles(self, symbol: str, candles: Sequence[Candle]) -> None:
        """Prime the buffer with a REST backfill before streaming begins."""
        sym = symbol.upper()
        buf: Deque[Candle] = deque(maxlen=self._max_candles)
        for candle in candles:
            if candle.is_closed:
                buf.append(candle)
        self._candles[sym] = buf

    # -- message folding ----------------------------------------------------

    def apply_kline(self, symbol: str, k: Mapping[str, Any]) -> bool:
        """Fold one kline payload; returns ``True`` if a closed candle was stored."""
        if not bool(k.get("x", False)):
            return False  # ignore still-open candles
        sym = symbol.upper()
        candle = _kline_to_candle(sym, k)
        buf = self._candles.setdefault(sym, deque(maxlen=self._max_candles))
        if buf and candle.open_time == buf[-1].open_time:
            buf[-1] = candle  # replace a re-sent final candle
        elif buf and candle.open_time < buf[-1].open_time:
            return False  # stale/out-of-order, ignore
        else:
            buf.append(candle)
        return True

    def apply_depth(self, symbol: str, payload: Mapping[str, Any]) -> None:
        """Fold a partial-book depth payload (``{bids, asks}``) for ``symbol``."""
        self._books[symbol.upper()] = OrderBook.from_levels(
            bids=payload.get("bids", []), asks=payload.get("asks", [])
        )

    def process_message(self, message: Mapping[str, Any], symbol: Optional[str] = None) -> None:
        """Route a raw or combined-stream message to the right handler.

        Handles the combined-stream envelope ``{"stream": ..., "data": ...}`` and
        raw event payloads. For depth payloads without an embedded symbol, the
        symbol is taken from the stream name or the ``symbol`` argument.
        """
        data = message.get("data", message)
        stream = message.get("stream")
        if "k" in data:  # kline event
            sym = symbol or data.get("s") or (_stream_symbol(stream) if stream else None)
            if sym is None:
                raise ValueError("kline message missing symbol")
            self.apply_kline(sym, data["k"])
            return
        if "bids" in data or "asks" in data:  # partial depth payload
            sym = symbol or data.get("s") or (_stream_symbol(stream) if stream else None)
            if sym is None:
                raise ValueError("depth message missing symbol")
            self.apply_depth(sym, data)
            return
        # Unknown message types are ignored (heartbeats, subscription acks, ...).

    # -- MarketDataPort -----------------------------------------------------

    def get_closed_candles(self, symbol: str, limit: int) -> List[Candle]:
        buf = self._candles.get(symbol.upper())
        if not buf:
            return []
        items = list(buf)
        return items[-limit:] if limit else items

    def get_order_book(self, symbol: str) -> OrderBook:
        # Returns an empty book when none has arrived yet; a conservative PnL on an
        # empty book evaluates to a hold, which is safe.
        return self._books.get(symbol.upper(), OrderBook(bids=(), asks=()))

    def has_order_book(self, symbol: str) -> bool:
        return symbol.upper() in self._books
