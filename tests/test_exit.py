"""Tests for the two-phase normal exit: RSI arming then minimum net profit."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.strategy.exit import (
    should_sell_normal,
    update_exit_arming,
)
from cryptobot.strategy.position import (
    PositionState,
    RealizedEntry,
    open_position,
)

from ._helpers import default_params, make_candles


def _position(overbought=70.0, min_net=Decimal("0.5"), cost="100", fees="0", sellable="1"):
    params = default_params(rsi_overbought=overbought, min_net_profit_pct=min_net)
    entry = RealizedEntry(
        filled_base_qty=Decimal(sellable),
        avg_entry_price=Decimal(cost),
        true_entry_cost=Decimal(cost),
        entry_fees_quote=Decimal(fees),
        sellable_base_qty=Decimal(sellable),
    )
    return open_position("BTCUSDT", params, entry, entry_candle_open_time=0)


# --- Phase 1: RSI arming ----------------------------------------------------

def test_rising_opens_arm_the_exit():
    pos = _position(overbought=70.0)
    # Strictly rising opens -> RSI == 100 > 70 -> arms.
    candles = make_candles([1, 2, 3, 4, 5])
    armed = update_exit_arming(pos, candles)
    assert armed is True
    assert pos.state is PositionState.EXIT_ARMED


def test_low_rsi_does_not_arm():
    pos = _position(overbought=70.0)
    # Flat opens -> RSI == 50, below overbought.
    candles = make_candles([5, 5, 5, 5, 5])
    armed = update_exit_arming(pos, candles)
    assert armed is False
    assert pos.state is PositionState.OPEN


def test_arming_is_strict_equality_does_not_arm():
    pos = _position(overbought=100.0)
    # Rising opens -> RSI == 100, which is NOT > 100.
    candles = make_candles([1, 2, 3, 4, 5])
    armed = update_exit_arming(pos, candles)
    assert armed is False
    assert pos.state is PositionState.OPEN


def test_arming_is_permanent_even_if_rsi_falls_back():
    pos = _position(overbought=70.0)
    update_exit_arming(pos, make_candles([1, 2, 3, 4, 5]))
    assert pos.state is PositionState.EXIT_ARMED
    armed_at = pos.exit_armed_candle_open_time

    # RSI now collapses (flat / falling opens). Must remain EXIT_ARMED.
    still = update_exit_arming(pos, make_candles([5, 5, 5, 5, 5]))
    assert still is True
    assert pos.state is PositionState.EXIT_ARMED
    assert pos.exit_armed_candle_open_time == armed_at


def test_arming_fails_closed_on_invalid_series():
    pos = _position(overbought=70.0)
    candles = make_candles([1, 2, 3, 4, 5])
    broken = candles[:2] + candles[3:]  # gap
    assert update_exit_arming(pos, broken) is False
    assert pos.state is PositionState.OPEN


def test_uses_snapshot_overbought_not_live_settings():
    pos = _position(overbought=70.0)
    # A later change to coin settings (new params object) is irrelevant; arming
    # reads pos.snapshot. If the (wrong) live value 100.0 were used, RSI==100
    # would NOT arm (100 > 100 is false); with the snapshot 70.0 it arms.
    _later = default_params(rsi_overbought=100.0)
    assert update_exit_arming(pos, make_candles([1, 2, 3, 4, 5])) is True


# --- Phase 2: minimum net profit -------------------------------------------

def test_no_sell_before_armed_even_if_profitable():
    pos = _position(min_net=Decimal("0.5"))
    assert pos.state is PositionState.OPEN
    book = OrderBook.from_levels(bids=[(1000, 10)])  # hugely profitable
    decision = should_sell_normal(pos, book, ExitCostModel())
    assert decision.sell is False
    assert "not EXIT_ARMED" in decision.reason


def test_armed_and_target_reached_sells():
    pos = _position(min_net=Decimal("0.5"), cost="100")
    pos.arm_exit(candle_open_time=1000)
    # invested = 100, target = 100 * 0.5/100 = 0.5. Bid 110 -> net 10 >= 0.5.
    book = OrderBook.from_levels(bids=[(110, 10)])
    decision = should_sell_normal(pos, book, ExitCostModel())
    assert decision.sell is True
    assert decision.target_net_pnl == Decimal("0.5")


def test_armed_but_below_target_holds():
    pos = _position(min_net=Decimal("0.5"), cost="100")
    pos.arm_exit(candle_open_time=1000)
    # Bid 100.4 -> net 0.4 < target 0.5 -> hold (no stop-loss, no forced sell).
    book = OrderBook.from_levels(bids=[(Decimal("100.4"), 10)])
    decision = should_sell_normal(pos, book, ExitCostModel())
    assert decision.sell is False
    assert decision.estimate.net_pnl == Decimal("0.4")


def test_target_at_exact_boundary_sells():
    pos = _position(min_net=Decimal("0.5"), cost="100")
    pos.arm_exit(candle_open_time=1000)
    # Bid 100.5 -> net exactly 0.5 == target -> sells (>= is inclusive).
    book = OrderBook.from_levels(bids=[(Decimal("100.5"), 10)])
    decision = should_sell_normal(pos, book, ExitCostModel())
    assert decision.sell is True


def test_loss_never_forces_a_sell():
    pos = _position(min_net=Decimal("0.5"), cost="100")
    pos.arm_exit(candle_open_time=1000)
    book = OrderBook.from_levels(bids=[(50, 10)])  # deep loss
    decision = should_sell_normal(pos, book, ExitCostModel())
    assert decision.sell is False
