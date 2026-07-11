"""Tests for withdrawal-mode exit (fixed 0.20% net profit, RSI ignored)."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.strategy.exit import (
    WITHDRAWAL_MIN_NET_PROFIT_PCT,
    should_sell_withdrawal,
)
from cryptobot.strategy.position import PositionState, RealizedEntry, open_position

from ._helpers import default_params


def _position(cost="100", fees="0", sellable="1"):
    entry = RealizedEntry(
        filled_base_qty=Decimal(sellable),
        avg_entry_price=Decimal(cost),
        true_entry_cost=Decimal(cost),
        entry_fees_quote=Decimal(fees),
        sellable_base_qty=Decimal(sellable),
    )
    return open_position("BTCUSDT", default_params(), entry, entry_candle_open_time=0)


def test_threshold_is_020_percent():
    assert WITHDRAWAL_MIN_NET_PROFIT_PCT == Decimal("0.20")


def test_sells_when_profit_reaches_020_percent():
    pos = _position(cost="100")
    # target = 100 * 0.20/100 = 0.20. Bid 100.2 -> net 0.20 == target -> sell.
    book = OrderBook.from_levels(bids=[(Decimal("100.2"), 10)])
    decision = should_sell_withdrawal(pos, book, ExitCostModel())
    assert decision.sell is True
    assert decision.target_net_pnl == Decimal("0.20")


def test_holds_below_020_percent():
    pos = _position(cost="100")
    # Bid 100.1 -> net 0.10 < 0.20 -> hold (never sell at a loss / below buffer).
    book = OrderBook.from_levels(bids=[(Decimal("100.1"), 10)])
    decision = should_sell_withdrawal(pos, book, ExitCostModel())
    assert decision.sell is False


def test_does_not_require_rsi_arming():
    # Position is OPEN (never armed) yet withdrawal mode still sells on profit.
    pos = _position(cost="100")
    assert pos.state is PositionState.OPEN
    book = OrderBook.from_levels(bids=[(105, 10)])
    decision = should_sell_withdrawal(pos, book, ExitCostModel())
    assert decision.sell is True


def test_uses_net_not_gross_price_difference():
    # Gross price is above entry, but fees+buffer push net below 0.20% -> hold.
    pos = _position(cost="100", fees="0")
    book = OrderBook.from_levels(bids=[(Decimal("100.2"), 10)])
    model = ExitCostModel(exit_fee_rate=Decimal("0.001"), safety_buffer_frac=Decimal("0.001"))
    decision = should_sell_withdrawal(pos, book, model)
    # gross 100.2; fees+buffer ~0.2004; net ~ -0.0004 < 0.20 target -> hold.
    assert decision.sell is False
    assert decision.estimate.net_pnl < Decimal("0.20")


def test_deep_loss_is_not_sold():
    pos = _position(cost="100")
    book = OrderBook.from_levels(bids=[(80, 10)])
    decision = should_sell_withdrawal(pos, book, ExitCostModel())
    assert decision.sell is False
