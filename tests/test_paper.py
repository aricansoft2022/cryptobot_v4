"""Tests for the paper-trading ledger account and simulated executor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptobot.execution.orderbook import OrderBook
from cryptobot.exchange.fills import RealizedPnL
from cryptobot.runtime.paper import LedgerAccount, PaperExecution
from cryptobot.runtime.service import TickReport
from cryptobot.strategy.position import RealizedEntry, open_position

from ._helpers import default_params, make_candles


def test_ledger_open_and_close():
    acct = LedgerAccount(Decimal("1000"))
    acct.record_open("BTCUSDT", Decimal("100"))
    assert acct.available_quote_balance() == Decimal("900")
    assert acct.used_capital("BTCUSDT") == Decimal("100")
    assert acct.open_and_reserved_slots("BTCUSDT") == 1

    acct.record_close("BTCUSDT", Decimal("100"), net_proceeds=Decimal("110"))
    assert acct.available_quote_balance() == Decimal("1010")
    assert acct.used_capital("BTCUSDT") == Decimal("0")
    assert acct.open_and_reserved_slots("BTCUSDT") == 0


def _position(cost="100"):
    entry = RealizedEntry(
        filled_base_qty=Decimal("1"), avg_entry_price=Decimal(cost),
        true_entry_cost=Decimal(cost), entry_fees_quote=Decimal("0"),
        sellable_base_qty=Decimal("1"),
    )
    return open_position("BTCUSDT", default_params(), entry, 0)


def test_ledger_apply_report():
    acct = LedgerAccount(Decimal("1000"))
    report = TickReport()
    report.entries.append(_position("100"))
    acct.apply_report(report)
    assert acct.available_quote_balance() == Decimal("900")

    exit_report = TickReport()
    pnl = RealizedPnL(
        gross_proceeds=Decimal("110"), exit_fees_quote=Decimal("0"),
        exit_qty=Decimal("1"), invested_quote_cost=Decimal("100"), net_pnl=Decimal("10"),
    )
    exit_report.exits.append((_position("100"), pnl))
    acct.apply_report(exit_report)
    assert acct.available_quote_balance() == Decimal("1010")
    assert acct.open_and_reserved_slots("BTCUSDT") == 0


class _MD:
    def __init__(self, book=None, candles=None):
        self._book = book if book is not None else OrderBook(bids=(), asks=())
        self._candles = candles or []

    def get_order_book(self, symbol):
        return self._book

    def get_closed_candles(self, symbol, limit):
        return self._candles[-limit:]


def test_paper_buy_fills_at_best_ask():
    md = _MD(book=OrderBook.from_levels(bids=[("99", "1")], asks=[("101", "1"), ("100", "1")]))
    fills = PaperExecution(md).market_buy("BTCUSDT", Decimal("100"))
    assert fills[0].price == Decimal("100")  # best (lowest) ask
    assert fills[0].qty == Decimal("1")


def test_paper_sell_fills_at_best_bid():
    md = _MD(book=OrderBook.from_levels(bids=[("99", "1"), ("100", "1")], asks=[("101", "1")]))
    fills = PaperExecution(md).market_sell("BTCUSDT", Decimal("2"))
    assert fills[0].price == Decimal("100")  # best (highest) bid
    assert fills[0].qty == Decimal("2")


def test_paper_falls_back_to_last_close():
    md = _MD(candles=make_candles([10, 11, 12], closes=[10, 11, 12]))
    fills = PaperExecution(md).market_buy("BTCUSDT", Decimal("24"))
    assert fills[0].price == Decimal("12")  # last close
    assert fills[0].qty == Decimal("2")


def test_paper_no_price_raises():
    with pytest.raises(LookupError):
        PaperExecution(_MD()).market_sell("BTCUSDT", Decimal("1"))
