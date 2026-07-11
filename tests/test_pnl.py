"""Tests for order-book sell estimation and conservative net-PnL."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel, estimate_net_pnl
from cryptobot.strategy.position import RealizedEntry, open_position

from ._helpers import default_params


def test_orderbook_sorts_bids_best_first():
    book = OrderBook.from_levels(bids=[(100, 1), (102, 1), (101, 1)])
    assert [p for p, _ in book.bids] == [Decimal("102"), Decimal("101"), Decimal("100")]


def test_sell_walks_multiple_levels():
    book = OrderBook.from_levels(bids=[(100, 1), (99, 2), (98, 5)])
    est = book.estimate_sell_proceeds(Decimal("2"))
    # 1 @ 100 + 1 @ 99 = 199
    assert est.gross_proceeds == Decimal("199")
    assert est.filled_qty == Decimal("2")
    assert est.fully_filled is True


def test_sell_insufficient_depth_is_conservative():
    book = OrderBook.from_levels(bids=[(100, 1)])
    est = book.estimate_sell_proceeds(Decimal("3"))
    assert est.gross_proceeds == Decimal("100")
    assert est.filled_qty == Decimal("1")
    assert est.fully_filled is False


def _position(sellable="1", cost="100", fees="0"):
    entry = RealizedEntry(
        filled_base_qty=Decimal(sellable),
        avg_entry_price=Decimal(cost) / Decimal(sellable) if Decimal(sellable) else Decimal("0"),
        true_entry_cost=Decimal(cost),
        entry_fees_quote=Decimal(fees),
        sellable_base_qty=Decimal(sellable),
    )
    return open_position("BTCUSDT", default_params(), entry, entry_candle_open_time=0)


def test_net_pnl_subtracts_all_costs():
    pos = _position(sellable="1", cost="100", fees="0.1")
    book = OrderBook.from_levels(bids=[(110, 10)])
    model = ExitCostModel(exit_fee_rate=Decimal("0.001"), safety_buffer_frac=Decimal("0.002"))
    est = estimate_net_pnl(pos, book, model)

    gross = Decimal("110")  # 1 @ 110
    exit_fees = gross * Decimal("0.001")   # 0.11
    buffer = gross * Decimal("0.002")      # 0.22
    invested = Decimal("100.1")            # cost + entry fees
    assert est.gross_proceeds == gross
    assert est.exit_fees == exit_fees
    assert est.safety_buffer == buffer
    assert est.invested_quote_cost == invested
    assert est.net_pnl == gross - exit_fees - buffer - invested


def test_net_pnl_can_be_negative():
    pos = _position(sellable="1", cost="100", fees="0")
    book = OrderBook.from_levels(bids=[(90, 10)])
    est = estimate_net_pnl(pos, book, ExitCostModel())
    assert est.net_pnl == Decimal("-10")


def test_uses_sellable_quantity_not_filled():
    # Entry bought 1.0 but only 0.5 is sellable; proceeds must use 0.5.
    entry = RealizedEntry(
        filled_base_qty=Decimal("1.0"),
        avg_entry_price=Decimal("100"),
        true_entry_cost=Decimal("100"),
        entry_fees_quote=Decimal("0"),
        sellable_base_qty=Decimal("0.5"),
    )
    pos = open_position("BTCUSDT", default_params(), entry, 0)
    book = OrderBook.from_levels(bids=[(200, 10)])
    est = estimate_net_pnl(pos, book, ExitCostModel())
    assert est.gross_proceeds == Decimal("100")  # 0.5 @ 200


def test_cost_model_rejects_negative_rates():
    with pytest.raises(ValueError):
        ExitCostModel(exit_fee_rate=Decimal("-0.001"))
    with pytest.raises(ValueError):
        ExitCostModel(safety_buffer_frac=Decimal("-0.001"))
