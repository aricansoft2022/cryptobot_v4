"""Integration tests for the TradingRuntime orchestrator using fake ports."""

from __future__ import annotations

from decimal import Decimal
from typing import List

import pytest

from cryptobot.execution.gates import OperationalGates
from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.exchange.fills import Fill
from cryptobot.strategy.engine import RuntimeMode
from cryptobot.strategy.position import PositionState, RealizedEntry, open_position
from cryptobot.runtime.orchestrator import TradingRuntime, split_symbol

from ._helpers import default_params, make_candles
from .test_entry import _fixture_candles


class FakeExchange:
    """Implements MarketDataPort + ExecutionPort against in-memory data."""

    def __init__(self, candles, order_book=None, buy_price=Decimal("100"), sell_price=Decimal("110")):
        self._candles = list(candles)
        self._book = order_book or OrderBook.from_levels(bids=[(sell_price, Decimal("1000"))])
        self.buy_price = buy_price
        self.sell_price = sell_price
        self.buys: List[tuple] = []
        self.sells: List[tuple] = []

    def get_closed_candles(self, symbol: str, limit: int):
        return self._candles[-limit:]

    def get_order_book(self, symbol: str) -> OrderBook:
        return self._book

    def market_buy(self, symbol: str, quote_amount: Decimal) -> List[Fill]:
        self.buys.append((symbol, quote_amount))
        return [Fill(self.buy_price, quote_amount / self.buy_price)]

    def market_sell(self, symbol: str, base_qty: Decimal) -> List[Fill]:
        self.sells.append((symbol, base_qty))
        return [Fill(self.sell_price, base_qty)]


def _open_gates(**overrides) -> OperationalGates:
    base = dict(
        runtime_running=True, trading_enabled=True, coin_active=True,
        coin_not_pending_delete=True, market_data_fresh=True, candles_contiguous=True,
        indicators_ready=True, not_already_processed=True, slot_available=True,
        capital_available=True, usdt_balance_sufficient=True, symbol_filters_ok=True,
        worker_holds_lease=True, reconciliation_clean=True, system_safe=True,
    )
    base.update(overrides)
    return OperationalGates(**base)


def test_split_symbol_variants():
    assert split_symbol("BTCUSDT") == ("BTC", "USDT")
    assert split_symbol("ETHBTC") == ("ETH", "BTC")
    with pytest.raises(ValueError):
        split_symbol("USDT")


def test_try_enter_opens_position_and_records_buy():
    ex = FakeExchange(_fixture_candles(), buy_price=Decimal("100"))
    rt = TradingRuntime(ex, ex)
    pos = rt.try_enter("BTCUSDT", default_params(), _open_gates(), quote_amount=Decimal("100"))
    assert pos is not None
    assert pos.symbol == "BTCUSDT"
    assert pos.entry.true_entry_cost == Decimal("100")
    assert ex.buys == [("BTCUSDT", Decimal("100"))]


def test_try_enter_blocked_by_gate():
    ex = FakeExchange(_fixture_candles())
    rt = TradingRuntime(ex, ex)
    pos = rt.try_enter(
        "BTCUSDT", default_params(), _open_gates(worker_holds_lease=False), Decimal("100")
    )
    assert pos is None
    assert ex.buys == []


def test_try_enter_idempotent_for_same_candle():
    ex = FakeExchange(_fixture_candles())
    rt = TradingRuntime(ex, ex)
    params = default_params()
    first = rt.try_enter("BTCUSDT", params, _open_gates(), Decimal("100"))
    second = rt.try_enter("BTCUSDT", params, _open_gates(), Decimal("100"))
    assert first is not None
    assert second is None  # same coin+candle already processed
    assert len(ex.buys) == 1


def test_try_enter_no_signal_returns_none():
    ex = FakeExchange(make_candles([5] * 12))  # flat -> no crossover
    rt = TradingRuntime(ex, ex)
    assert rt.try_enter("BTCUSDT", default_params(), _open_gates(), Decimal("100")) is None


def test_withdrawal_mode_blocks_entry():
    ex = FakeExchange(_fixture_candles())
    rt = TradingRuntime(ex, ex)
    pos = rt.try_enter(
        "BTCUSDT", default_params(), _open_gates(), Decimal("100"), mode=RuntimeMode.WITHDRAWAL_REQUESTED
    )
    assert pos is None


def _position(cost="100"):
    params = default_params(rsi_overbought=70.0, min_net_profit_pct=Decimal("0.5"))
    entry = RealizedEntry(
        filled_base_qty=Decimal("1"), avg_entry_price=Decimal(cost),
        true_entry_cost=Decimal(cost), entry_fees_quote=Decimal("0"),
        sellable_base_qty=Decimal("1"),
    )
    return open_position("BTCUSDT", params, entry, entry_candle_open_time=0)


def test_try_exit_arms_and_sells_realizing_pnl():
    pos = _position(cost="100")
    # Rising opens arm the exit; sell price 110 -> realized net 10.
    ex = FakeExchange(make_candles(list(range(1, 13))), sell_price=Decimal("110"))
    rt = TradingRuntime(ex, ex)
    pnl = rt.try_exit(pos, ExitCostModel(), RuntimeMode.RUNNING)
    assert pos.state is PositionState.EXIT_ARMED or pos.state is PositionState.CLOSED
    assert pos.state is PositionState.CLOSED
    assert pnl is not None
    assert pnl.net_pnl == Decimal("10")
    assert ex.sells == [("BTCUSDT", Decimal("1"))]


def test_try_exit_holds_when_not_armed():
    pos = _position(cost="100")
    ex = FakeExchange(make_candles([5] * 12), sell_price=Decimal("1000"))  # never arms
    rt = TradingRuntime(ex, ex)
    pnl = rt.try_exit(pos, ExitCostModel(), RuntimeMode.RUNNING)
    assert pnl is None
    assert pos.state is PositionState.OPEN
    assert ex.sells == []


def test_try_exit_withdrawal_sells_without_arming():
    pos = _position(cost="100")
    ex = FakeExchange(make_candles([5] * 12), sell_price=Decimal("105"))  # would never arm
    rt = TradingRuntime(ex, ex)
    pnl = rt.try_exit(pos, ExitCostModel(), RuntimeMode.WITHDRAWAL_REQUESTED)
    assert pnl is not None
    assert pos.state is PositionState.CLOSED
    assert pnl.net_pnl == Decimal("5")
