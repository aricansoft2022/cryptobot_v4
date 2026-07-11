"""Tests for the config-driven TradingService scheduler loop."""

from __future__ import annotations

from decimal import Decimal
from typing import List

from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.exchange.fills import Fill
from cryptobot.strategy.position import PositionState
from cryptobot.runtime.service import (
    OperationalStatus,
    ServiceConfig,
    TradingService,
)

from ._helpers import default_params, make_candles
from .test_entry import _fixture_candles


class FakeMarketData:
    def __init__(self):
        self.candles = {}
        self.books = {}

    def get_closed_candles(self, symbol, limit):
        return self.candles.get(symbol, [])[-limit:]

    def get_order_book(self, symbol):
        return self.books.get(symbol, OrderBook(bids=(), asks=()))


class FakeAccount:
    def __init__(self, quote=Decimal("1000"), used=Decimal("0"), slots=0):
        self.quote = quote
        self.used = used
        self.slots = slots

    def available_quote_balance(self):
        return self.quote

    def used_capital(self, symbol):
        return self.used

    def open_and_reserved_slots(self, symbol):
        return self.slots


class FakeClock:
    def __init__(self, now_ms=480_000):
        self.now = now_ms

    def now_ms(self):
        return self.now


class FakeExecution:
    def __init__(self, buy_price=Decimal("100"), sell_price=Decimal("110")):
        self.buy_price = buy_price
        self.sell_price = sell_price
        self.buys: List[tuple] = []
        self.sells: List[tuple] = []

    def market_buy(self, symbol, quote_amount):
        self.buys.append((symbol, quote_amount))
        return [Fill(self.buy_price, quote_amount / self.buy_price, Decimal("0"), "USDT")]

    def market_sell(self, symbol, base_qty):
        self.sells.append((symbol, base_qty))
        return [Fill(self.sell_price, base_qty, Decimal("0"), "USDT")]


def _service(md=None, account=None, execution=None, clock=None, params=None):
    md = md or FakeMarketData()
    if "BTCUSDT" not in md.candles:
        md.candles["BTCUSDT"] = _fixture_candles()
    params = params or default_params(capital_limit_usdt=Decimal("100"), slot_count=1)
    config = ServiceConfig(coins={"BTCUSDT": params}, cost_model=ExitCostModel())
    return TradingService(
        md, execution or FakeExecution(), account or FakeAccount(),
        clock or FakeClock(), config,
    ), md


def test_tick_enters_when_all_green():
    execution = FakeExecution()
    svc, _ = _service(execution=execution)
    report = svc.tick()
    assert len(report.entries) == 1
    assert execution.buys == [("BTCUSDT", Decimal("100"))]
    assert len(svc.open_positions("BTCUSDT")) == 1


def test_tick_idempotent_for_same_candle():
    execution = FakeExecution()
    svc, _ = _service(execution=execution)
    svc.tick()
    second = svc.tick()
    assert second.entries == []
    assert len(execution.buys) == 1


def test_status_gate_blocks_entry():
    svc, _ = _service()
    report = svc.tick(OperationalStatus(runtime_running=False))
    assert report.entries == []


def test_inactive_coin_blocks_entry():
    svc, _ = _service()
    report = svc.tick(OperationalStatus(inactive_coins=frozenset({"BTCUSDT"})))
    assert report.entries == []


def test_pending_delete_blocks_entry():
    svc, _ = _service()
    report = svc.tick(OperationalStatus(pending_delete_coins=frozenset({"BTCUSDT"})))
    assert report.entries == []


def test_stale_market_data_blocks_entry():
    # Clock far past the last candle's close -> market_data_fresh gate closed.
    svc, _ = _service(clock=FakeClock(now_ms=999_999_999))
    assert svc.tick().entries == []


def test_insufficient_balance_blocks_entry():
    svc, _ = _service(account=FakeAccount(quote=Decimal("1")))  # < order size 100
    assert svc.tick().entries == []


def test_full_slots_size_zero_blocks_entry():
    # slot_count 1 and 1 slot already used -> sizing returns 0 -> no entry.
    svc, _ = _service(account=FakeAccount(slots=1))
    assert svc.tick().entries == []


def test_arm_then_exit_realizes_pnl():
    execution = FakeExecution(sell_price=Decimal("110"))
    svc, md = _service(execution=execution)
    svc.tick()  # enter
    assert svc.open_positions("BTCUSDT")[0].state is PositionState.OPEN

    # Rising opens arm; profitable book triggers the sell on the next tick.
    md.candles["BTCUSDT"] = make_candles(list(range(1, 13)))
    md.books["BTCUSDT"] = OrderBook.from_levels(bids=[(Decimal("110"), Decimal("1000"))])
    report = svc.tick()
    assert len(report.exits) == 1
    _, pnl = report.exits[0]
    assert pnl.net_pnl == Decimal("10")
    assert svc.open_positions("BTCUSDT") == []
    assert execution.sells == [("BTCUSDT", Decimal("1"))]


def test_withdrawal_mode_blocks_entries_and_exits_on_profit():
    execution = FakeExecution(sell_price=Decimal("105"))
    svc, md = _service(execution=execution)
    svc.tick()  # open a position first
    assert len(svc.open_positions("BTCUSDT")) == 1

    svc.request_withdrawal()
    # Even flat candles (never arm) must exit in withdrawal mode on >= 0.20%.
    md.candles["BTCUSDT"] = make_candles([5] * 12)
    md.books["BTCUSDT"] = OrderBook.from_levels(bids=[(Decimal("105"), Decimal("1000"))])
    report = svc.tick()
    assert report.entries == []  # no new entries in withdrawal mode
    assert len(report.exits) == 1
    assert svc.open_positions("BTCUSDT") == []


def test_run_loops_with_injected_sleep():
    svc, _ = _service()
    slept: List[float] = []
    reports = svc.run(3, sleep_fn=slept.append, interval_s=0.5)
    assert len(reports) == 3
    assert slept == [0.5, 0.5]  # sleeps between ticks, not after the last
