"""Tests for operational gates and per-candle idempotency."""

from __future__ import annotations

from decimal import Decimal

from cryptobot.execution.gates import (
    OperationalGates,
    ProcessedCandleGuard,
    capital_below_limit,
    slots_below_limit,
)

from ._helpers import default_params


def _all_open(**overrides) -> OperationalGates:
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


def test_all_open_true_when_every_gate_open():
    assert _all_open().all_open() is True
    assert _all_open().blocked_reasons() == []


def test_single_closed_gate_blocks():
    gates = _all_open(worker_holds_lease=False)
    assert gates.all_open() is False
    assert gates.blocked_reasons() == ["worker_holds_lease"]


def test_multiple_closed_gates_all_reported():
    gates = _all_open(runtime_running=False, system_safe=False)
    assert gates.all_open() is False
    assert set(gates.blocked_reasons()) == {"runtime_running", "system_safe"}


def test_idempotency_guard_blocks_second_time():
    guard = ProcessedCandleGuard()
    assert guard.already_processed("BTCUSDT", 1000) is False
    guard.mark_processed("BTCUSDT", 1000)
    assert guard.already_processed("BTCUSDT", 1000) is True
    # Different candle / different symbol are independent.
    assert guard.already_processed("BTCUSDT", 2000) is False
    assert guard.already_processed("ETHUSDT", 1000) is False


def test_slots_below_limit():
    params = default_params(slot_count=3)
    assert slots_below_limit(2, params) is True
    assert slots_below_limit(3, params) is False
    assert slots_below_limit(4, params) is False


def test_capital_below_limit():
    params = default_params(capital_limit_usdt=Decimal("1000"))
    assert capital_below_limit(Decimal("999"), params) is True
    assert capital_below_limit(Decimal("1000"), params) is False
    assert capital_below_limit(Decimal("1500"), params) is False
