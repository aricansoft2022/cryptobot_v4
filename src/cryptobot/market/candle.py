"""The 1-minute closed-candle model used for every signal computation.

Per the specification, all signal math runs exclusively on candles that are:

* fully closed,
* of the same symbol,
* 1-minute interval,
* chronologically ordered,
* free of duplicates,
* free of data gaps.

This module defines the immutable :class:`Candle` value type. The
:mod:`cryptobot.market.validation` module enforces the series-level guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The one and only candle interval used by the strategy, in milliseconds.
INTERVAL_MS: int = 60_000


@dataclass(frozen=True)
class Candle:
    """A single, immutable OHLCV candle.

    Attributes:
        symbol: The trading symbol the candle belongs to (e.g. ``"BTCUSDT"``).
        open_time: Candle open time in epoch milliseconds. For 1-minute candles
            consecutive candles differ by exactly :data:`INTERVAL_MS`.
        open: Open price. RSI is computed from this field only.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Base-asset volume for the candle (used by RSI-VWMA weighting).
        is_closed: Whether the candle is fully closed. Signals may only be
            derived from closed candles.
    """

    symbol: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(
                f"candle high ({self.high}) is below low ({self.low}) "
                f"for {self.symbol} @ {self.open_time}"
            )
        if self.volume < 0:
            raise ValueError(
                f"candle volume ({self.volume}) is negative "
                f"for {self.symbol} @ {self.open_time}"
            )

    @property
    def range(self) -> float:
        """The high-low range of the candle (used by ADR)."""
        return self.high - self.low
