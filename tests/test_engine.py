"""Integration tests for the top-level engine: signal + gates, and exit routing."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.execution.gates import OperationalGates, ProcessedCandleGuard
from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.strategy.engine import (
    RuntimeMode,
    evaluate_buy,
    evaluate_exit,
)
from cryptobot.strategy.position import PositionState, RealizedEntry, open_position

from ._helpers import default_params, make_candles
from .test_entry import _fixture_candles


def _open_gates(**overrides) -> OperationalGates:
    base = dict(
        runtime_running=True,
        trading_enabled=True,
        coin_active=True,
        coin_not_pending_delete=True,
        market_data_fresh=True,
        candles_contiguous=True,
        indicators_ready=True,
        not_already_processed=True,
        slot_available=True,
        capital_available=True,
        usdt_balance_sufficient=True,
        symbol_filters_ok=True,
        worker_holds_lease=True,
        reconciliation_clean=True,
        system_safe=True,
    )
    base.update(overrides)
    return OperationalGates(**base)


def test_buy_when_signal_and_gates_open():
    decision = evaluate_buy(
        "BTCUSDT", _fixture_candles(), default_params(), _open_gates()
    )
    assert decision.evaluation.signal is True
    assert decision.buy is True


def test_no_buy_when_a_gate_is_closed():
    decision = evaluate_buy(
        "BTCUSDT", _fixture_candles(), default_params(), _open_gates(worker_holds_lease=False)
    )
    assert decision.evaluation.signal is True  # signal still present
    assert decision.buy is False
    assert "gates closed" in decision.reason


def test_no_buy_without_signal_even_if_gates_open():
    # Flat market -> no crossover -> no signal.
    candles = make_candles([5] * 10)
    decision = evaluate_buy("BTCUSDT", candles, default_params(), _open_gates())
    assert decision.evaluation.signal is False
    assert decision.buy is False


def test_idempotency_blocks_second_buy_same_candle():
    guard = ProcessedCandleGuard()
    candles = _fixture_candles()
    params = default_params()

    first = evaluate_buy("BTCUSDT", candles, params, _open_gates(), guard)
    assert first.buy is True
    # Simulate acting on the buy.
    guard.mark_processed("BTCUSDT", first.evaluation.candle_open_time)

    second = evaluate_buy("BTCUSDT", candles, params, _open_gates(), guard)
    assert second.buy is False
    assert second.already_processed is True


def test_withdrawal_mode_blocks_all_entries():
    decision = evaluate_buy(
        "BTCUSDT",
        _fixture_candles(),
        default_params(),
        _open_gates(),
        mode=RuntimeMode.WITHDRAWAL_REQUESTED,
    )
    assert decision.buy is False
    assert "withdrawal mode" in decision.reason


# --- Exit routing -----------------------------------------------------------

def _position(cost="100", min_net=Decimal("0.5")):
    params = default_params(rsi_overbought=70.0, min_net_profit_pct=min_net)
    entry = RealizedEntry(
        filled_base_qty=Decimal("1"),
        avg_entry_price=Decimal(cost),
        true_entry_cost=Decimal(cost),
        entry_fees_quote=Decimal("0"),
        sellable_base_qty=Decimal("1"),
    )
    return open_position("BTCUSDT", params, entry, entry_candle_open_time=0)


def test_evaluate_exit_normal_arms_then_sells():
    pos = _position(cost="100")
    # Rising opens arm the exit; profitable book triggers the sell.
    candles = make_candles([1, 2, 3, 4, 5])
    book = OrderBook.from_levels(bids=[(110, 10)])
    decision = evaluate_exit(pos, candles, book, ExitCostModel(), RuntimeMode.RUNNING)
    assert pos.state is PositionState.EXIT_ARMED
    assert decision.sell is True


def test_evaluate_exit_normal_holds_until_armed():
    pos = _position(cost="100")
    # Flat opens never arm; even a profitable book must not sell.
    candles = make_candles([5, 5, 5, 5, 5])
    book = OrderBook.from_levels(bids=[(1000, 10)])
    decision = evaluate_exit(pos, candles, book, ExitCostModel(), RuntimeMode.RUNNING)
    assert pos.state is PositionState.OPEN
    assert decision.sell is False


def test_evaluate_exit_withdrawal_ignores_arming():
    pos = _position(cost="100")
    candles = make_candles([5, 5, 5, 5, 5])  # would never arm
    book = OrderBook.from_levels(bids=[(105, 10)])
    decision = evaluate_exit(
        pos, candles, book, ExitCostModel(), RuntimeMode.WITHDRAWAL_REQUESTED
    )
    # Not armed, but withdrawal mode sells on >= 0.20% net profit.
    assert pos.state is PositionState.OPEN
    assert decision.sell is True
    assert decision.target_net_pnl == Decimal("0.20")
