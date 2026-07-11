"""Tests for the position model, snapshot immutability and the state machine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptobot.strategy.position import (
    PositionState,
    RealizedEntry,
    open_position,
)

from ._helpers import default_params


def _entry() -> RealizedEntry:
    return RealizedEntry(
        filled_base_qty=Decimal("1.0"),
        avg_entry_price=Decimal("100"),
        true_entry_cost=Decimal("100"),
        entry_fees_quote=Decimal("0.1"),
        sellable_base_qty=Decimal("0.999"),
    )


def test_invested_quote_cost_is_notional_plus_fees():
    entry = _entry()
    assert entry.invested_quote_cost == Decimal("100.1")


def test_snapshot_is_independent_of_later_setting_changes():
    params = default_params(rsi_overbought=70.0, min_net_profit_pct=Decimal("0.5"))
    pos = open_position("BTCUSDT", params, _entry(), entry_candle_open_time=1000)

    # "Change the coin settings" == build a new parameter object for the coin.
    _new_settings = default_params(rsi_overbought=55.0, min_net_profit_pct=Decimal("2.0"))

    # The open position keeps its original snapshot values.
    assert pos.snapshot.rsi_overbought == 70.0
    assert pos.snapshot.min_net_profit_pct == Decimal("0.5")


def test_arming_is_permanent_and_keeps_first_candle():
    pos = open_position("BTCUSDT", default_params(), _entry(), entry_candle_open_time=1000)
    assert pos.state is PositionState.OPEN

    pos.arm_exit(candle_open_time=2000)
    assert pos.state is PositionState.EXIT_ARMED
    assert pos.exit_armed_candle_open_time == 2000

    # Re-arming is a no-op and must not overwrite the original arming candle.
    pos.arm_exit(candle_open_time=3000)
    assert pos.exit_armed_candle_open_time == 2000
    assert pos.is_exit_armed


def test_cannot_arm_closed_position():
    pos = open_position("BTCUSDT", default_params(), _entry(), entry_candle_open_time=1000)
    pos.mark_closed()
    with pytest.raises(ValueError):
        pos.arm_exit(candle_open_time=2000)


def test_realized_entry_rejects_sellable_gt_filled():
    with pytest.raises(ValueError):
        RealizedEntry(
            filled_base_qty=Decimal("1.0"),
            avg_entry_price=Decimal("100"),
            true_entry_cost=Decimal("100"),
            entry_fees_quote=Decimal("0"),
            sellable_base_qty=Decimal("1.5"),
        )
