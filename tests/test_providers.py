"""Tests for operational providers (clock, sizing, freshness)."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.market.candle import INTERVAL_MS
from cryptobot.runtime.providers import (
    SystemClock,
    equal_slot_quote_amount,
    is_market_data_fresh,
)

from ._helpers import default_params, make_candles


def test_system_clock_returns_int_ms():
    now = SystemClock().now_ms()
    assert isinstance(now, int)
    assert now > 1_000_000_000_000  # well past 2001 in ms


def test_equal_slot_sizing_divides_capital():
    params = default_params(capital_limit_usdt=Decimal("1000"), slot_count=4)
    # 2 slots used, no capital used yet -> per-slot share = 1000/4 = 250.
    assert equal_slot_quote_amount(params, open_and_reserved_slots=2, used_capital_usdt=Decimal("0")) == Decimal("250")


def test_equal_slot_sizing_capped_by_remaining_capital():
    params = default_params(capital_limit_usdt=Decimal("1000"), slot_count=4)
    # Only 100 capital left -> capped below the 250 per-slot share.
    assert equal_slot_quote_amount(params, 1, Decimal("900")) == Decimal("100")


def test_equal_slot_sizing_zero_when_no_slot():
    params = default_params(slot_count=3)
    assert equal_slot_quote_amount(params, open_and_reserved_slots=3, used_capital_usdt=Decimal("0")) == Decimal("0")


def test_equal_slot_sizing_zero_when_no_capital():
    params = default_params(capital_limit_usdt=Decimal("1000"), slot_count=4)
    assert equal_slot_quote_amount(params, 1, Decimal("1000")) == Decimal("0")


def test_market_data_fresh_within_lag():
    candles = make_candles([1, 2, 3])  # last open_time = 2*INTERVAL_MS
    last_close = 2 * INTERVAL_MS + INTERVAL_MS - 1
    assert is_market_data_fresh(candles, now_ms=last_close + 1) is True


def test_market_data_stale_beyond_lag():
    candles = make_candles([1, 2, 3])
    last_close = 2 * INTERVAL_MS + INTERVAL_MS - 1
    assert is_market_data_fresh(candles, now_ms=last_close + 10 * INTERVAL_MS) is False


def test_market_data_fresh_empty_is_false():
    assert is_market_data_fresh([], now_ms=123) is False
