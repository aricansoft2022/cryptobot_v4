"""Tests for Binance symbol filters (rounding + order acceptance)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptobot.exchange.filters import SymbolFilters


def _filters(**overrides) -> SymbolFilters:
    base = dict(
        symbol="BTCUSDT",
        step_size=Decimal("0.00001"),
        min_qty=Decimal("0.00001"),
        max_qty=Decimal("9000"),
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("1000000"),
        min_notional=Decimal("10"),
    )
    base.update(overrides)
    return SymbolFilters(**base)


def test_round_quantity_floors_to_step():
    f = _filters()
    assert f.round_quantity("0.123456789") == Decimal("0.12345")
    assert f.round_quantity("0.00001") == Decimal("0.00001")


def test_round_price_floors_to_tick():
    f = _filters()
    assert f.round_price("27123.456") == Decimal("27123.45")


def test_quantity_bounds_and_grid():
    f = _filters()
    assert f.quantity_ok("0.000005") is False   # below minQty
    assert f.quantity_ok("9000.00001") is False  # above maxQty
    assert f.quantity_ok("0.000015") is False    # off the step grid
    assert f.quantity_ok("0.00002") is True


def test_notional_floor():
    f = _filters(min_notional=Decimal("10"))
    assert f.notional_ok("100000", "0.00005") is False  # 5 < 10
    assert f.notional_ok("100000", "0.0001") is True     # 10 == 10


def test_accepts_order_requires_qty_and_notional():
    f = _filters()
    assert f.accepts_order("100000", "0.0002") is True
    # On-grid qty but notional too small.
    assert f.accepts_order("1", "0.0002") is False


def test_from_exchange_info_prefers_market_lot_size():
    info = {
        "symbol": "BTCUSDT",
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
            {"filterType": "MARKET_LOT_SIZE", "minQty": "0.01", "maxQty": "50", "stepSize": "0.01"},
            {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1e6", "tickSize": "0.01"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }
    f = SymbolFilters.from_exchange_info_symbol(info)
    assert f.step_size == Decimal("0.01")  # market lot size wins
    assert f.min_qty == Decimal("0.01")
    assert f.min_notional == Decimal("5")


def test_from_exchange_info_accepts_legacy_min_notional():
    info = {
        "symbol": "ETHUSDT",
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.0001", "maxQty": "1000", "stepSize": "0.0001"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
        ],
    }
    f = SymbolFilters.from_exchange_info_symbol(info)
    assert f.min_notional == Decimal("10")
    assert f.tick_size == Decimal("0")  # no PRICE_FILTER -> default 0


def test_missing_lot_size_raises():
    with pytest.raises(ValueError):
        SymbolFilters.from_exchange_info_symbol({"symbol": "X", "filters": []})
