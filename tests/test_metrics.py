"""Tests for the monitoring metrics tracker and status snapshot."""

from __future__ import annotations

import json
from decimal import Decimal

from cryptobot.execution.orderbook import OrderBook
from cryptobot.execution.pnl import ExitCostModel
from cryptobot.exchange.fills import RealizedPnL
from cryptobot.runtime.metrics import MetricsTracker, build_status
from cryptobot.runtime.service import TickReport
from cryptobot.strategy.position import RealizedEntry, open_position

from ._helpers import default_params


def _position(symbol="BTCUSDT", cost="100", qty="1"):
    entry = RealizedEntry(
        filled_base_qty=Decimal(qty), avg_entry_price=Decimal(cost),
        true_entry_cost=Decimal(cost), entry_fees_quote=Decimal("0"),
        sellable_base_qty=Decimal(qty),
    )
    return open_position(symbol, default_params(), entry, entry_candle_open_time=1000)


def _pnl(net):
    return RealizedPnL(
        gross_proceeds=Decimal("0"), exit_fees_quote=Decimal("0"),
        exit_qty=Decimal("1"), invested_quote_cost=Decimal("100"), net_pnl=Decimal(net),
    )


def test_metrics_accumulates_trades():
    metrics = MetricsTracker()
    win = TickReport()
    win.exits.append((_position(), _pnl("10")))
    loss = TickReport()
    loss.exits.append((_position(), _pnl("-4")))
    metrics.record_report(win, now_ms=1)
    metrics.record_report(loss, now_ms=2)

    assert metrics.num_trades == 2
    assert metrics.realized_net_pnl == Decimal("6")
    assert metrics.wins == 1
    assert metrics.losses == 1
    assert metrics.win_rate == 0.5
    assert metrics.trades[0].closed_at_ms == 1


class _FakeService:
    def __init__(self, positions):
        self._positions = positions

    def open_positions(self, symbol):
        return self._positions.get(symbol, [])


class _FakeAccount:
    def __init__(self, balance):
        self._balance = Decimal(balance)

    def available_quote_balance(self):
        return self._balance


class _FakeMarketData:
    def __init__(self, book):
        self._book = book

    def get_order_book(self, symbol):
        return self._book


def test_build_status_with_open_position_and_book():
    pos = _position(cost="100", qty="1")
    service = _FakeService({"BTCUSDT": [pos]})
    account = _FakeAccount("900")
    book = OrderBook.from_levels(bids=[("110", "1000")])
    metrics = MetricsTracker()

    snap = build_status(["BTCUSDT"], service, account, _FakeMarketData(book), ExitCostModel(), metrics, now_ms=123)

    assert snap.available_quote == Decimal("900")
    assert len(snap.open_positions) == 1
    view = snap.open_positions[0]
    assert view.state == "OPEN"
    assert view.estimated_net_pnl == Decimal("10")  # sell 1 @ 110 minus invested 100
    assert snap.open_invested_quote == Decimal("100")
    assert snap.estimated_unrealized_net_pnl == Decimal("10")
    assert snap.generated_at_ms == 123


def test_build_status_empty_book_gives_none_estimate():
    pos = _position()
    service = _FakeService({"BTCUSDT": [pos]})
    snap = build_status(
        ["BTCUSDT"], service, _FakeAccount("1000"),
        _FakeMarketData(OrderBook(bids=(), asks=())), ExitCostModel(), MetricsTracker(), now_ms=1,
    )
    assert snap.open_positions[0].estimated_net_pnl is None
    assert snap.estimated_unrealized_net_pnl == Decimal("0")


def test_snapshot_is_json_serializable():
    pos = _position()
    service = _FakeService({"BTCUSDT": [pos]})
    book = OrderBook.from_levels(bids=[("110", "1000")])
    metrics = MetricsTracker()
    win = TickReport()
    win.exits.append((_position(), _pnl("5")))
    metrics.record_report(win, now_ms=1)

    snap = build_status(["BTCUSDT"], service, _FakeAccount("900"), _FakeMarketData(book), ExitCostModel(), metrics, now_ms=1)
    payload = snap.as_dict()
    text = json.dumps(payload)  # must not raise
    reloaded = json.loads(text)
    assert reloaded["realized_trades"] == 1
    assert reloaded["realized_net_pnl"] == "5"
    assert reloaded["open_positions"][0]["state"] == "OPEN"
    assert reloaded["available_quote"] == "900"
