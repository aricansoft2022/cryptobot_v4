"""Tests for strict candle-series validation."""

from __future__ import annotations

import pytest

from cryptobot.market.candle import INTERVAL_MS, Candle
from cryptobot.market.validation import (
    CandleSeriesError,
    ensure_valid_series,
    is_valid_series,
    validate_series,
)

from ._helpers import make_candles


def test_valid_contiguous_series_passes():
    candles = make_candles([1, 2, 3, 4])
    assert validate_series(candles) == []
    assert is_valid_series(candles)
    ensure_valid_series(candles)  # does not raise


def test_empty_series_is_invalid():
    assert validate_series([]) == ["candle series is empty"]
    assert not is_valid_series([])
    with pytest.raises(CandleSeriesError):
        ensure_valid_series([])


def test_unclosed_candle_is_invalid():
    candles = make_candles([1, 2, 3])
    candles[-1] = Candle("BTCUSDT", 2 * INTERVAL_MS, 3, 4, 2, 3, 1.0, is_closed=False)
    problems = validate_series(candles)
    assert any("not closed" in p for p in problems)


def test_mixed_symbols_invalid():
    candles = make_candles([1, 2, 3])
    bad = candles[1]
    candles[1] = Candle("ETHUSDT", bad.open_time, bad.open, bad.high, bad.low, bad.close, bad.volume)
    problems = validate_series(candles)
    assert any("symbol" in p for p in problems)


def test_gap_detected():
    candles = make_candles([1, 2, 3])
    # Push the last candle one extra minute into the future -> a 1-candle gap.
    last = candles[-1]
    candles[-1] = Candle(
        last.symbol, last.open_time + INTERVAL_MS, last.open, last.high, last.low, last.close, last.volume
    )
    problems = validate_series(candles)
    assert any("gap" in p for p in problems)


def test_duplicate_open_time_detected():
    candles = make_candles([1, 2, 3])
    dup = candles[1]
    candles[2] = Candle(dup.symbol, dup.open_time, 3, 4, 2, 3, 1.0)
    problems = validate_series(candles)
    assert any("duplicate" in p for p in problems)


def test_out_of_order_detected():
    candles = make_candles([1, 2, 3])
    candles[1], candles[2] = candles[2], candles[1]
    problems = validate_series(candles)
    assert problems  # ordering / gap violation reported


def test_ensure_valid_raises_on_gap():
    candles = make_candles([1, 2])
    last = candles[-1]
    candles[-1] = Candle(
        last.symbol, last.open_time + INTERVAL_MS, last.open, last.high, last.low, last.close, last.volume
    )
    with pytest.raises(CandleSeriesError):
        ensure_valid_series(candles)


def test_candle_rejects_high_below_low():
    with pytest.raises(ValueError):
        Candle("BTCUSDT", 0, 10, 5, 8, 9, 1.0)  # high 5 < low 8


def test_candle_rejects_negative_volume():
    with pytest.raises(ValueError):
        Candle("BTCUSDT", 0, 10, 11, 9, 10, -1.0)
