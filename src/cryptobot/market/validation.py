"""Strict validation of a candle series before any signal is computed.

The strategy must *never* produce an entry or exit signal on missing or stale
market data. This module enforces every series-level guarantee required by the
spec. Any violation is reported through :class:`CandleSeriesError`; callers are
expected to treat a validation failure as *fail-closed* (no signal).
"""

from __future__ import annotations

from typing import List, Sequence

from .candle import INTERVAL_MS, Candle


class CandleSeriesError(ValueError):
    """Raised when a candle series violates a signal-eligibility guarantee."""


def validate_series(candles: Sequence[Candle]) -> List[str]:
    """Return a list of validation problems for ``candles`` (empty == valid).

    The checks, all mandated by the spec, are:

    * the series is non-empty,
    * every candle is closed,
    * every candle shares the same symbol,
    * candles are strictly ordered by ``open_time``,
    * there are no duplicate ``open_time`` values,
    * consecutive candles are exactly one minute apart (no gaps).
    """
    problems: List[str] = []

    if not candles:
        return ["candle series is empty"]

    symbol = candles[0].symbol
    for index, candle in enumerate(candles):
        if not candle.is_closed:
            problems.append(
                f"candle at index {index} (open_time={candle.open_time}) is not closed"
            )
        if candle.symbol != symbol:
            problems.append(
                f"candle at index {index} has symbol {candle.symbol!r}, "
                f"expected {symbol!r}"
            )

    for index in range(1, len(candles)):
        prev = candles[index - 1]
        curr = candles[index]
        delta = curr.open_time - prev.open_time
        if delta == 0:
            problems.append(
                f"duplicate open_time {curr.open_time} at index {index}"
            )
        elif delta < 0:
            problems.append(
                f"candles out of order at index {index}: "
                f"{prev.open_time} -> {curr.open_time}"
            )
        elif delta != INTERVAL_MS:
            missing = (delta // INTERVAL_MS) - 1 if delta % INTERVAL_MS == 0 else None
            detail = f" ({missing} missing candle(s))" if missing else ""
            problems.append(
                f"data gap between index {index - 1} and {index}: "
                f"{prev.open_time} -> {curr.open_time}{detail}"
            )

    return problems


def is_valid_series(candles: Sequence[Candle]) -> bool:
    """Return ``True`` if ``candles`` satisfies every signal-eligibility rule."""
    return not validate_series(candles)


def ensure_valid_series(candles: Sequence[Candle]) -> None:
    """Raise :class:`CandleSeriesError` if ``candles`` is not signal-eligible."""
    problems = validate_series(candles)
    if problems:
        raise CandleSeriesError("; ".join(problems))
