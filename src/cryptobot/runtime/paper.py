"""Paper-trading providers: an in-memory account ledger and a simulated executor.

These let the service run end-to-end against real (read-only) market data without
placing any live orders — the safe default for a runnable entrypoint. Neither
touches the strategy signal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from ..exchange.fills import Fill
from .ports import MarketDataPort
from .service import TickReport


def _as_decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class LedgerAccount:
    """An ``AccountPort`` backed by a simple in-memory ledger.

    Cash falls by the invested quote at open and rises by net proceeds at close;
    per-symbol committed capital and slot counts track open positions. Update it
    from each tick via :meth:`apply_report`.
    """

    def __init__(self, quote_balance: Any) -> None:
        self._quote = _as_decimal(quote_balance)
        self._used: Dict[str, Decimal] = {}
        self._slots: Dict[str, int] = {}

    def available_quote_balance(self) -> Decimal:
        return self._quote

    def used_capital(self, symbol: str) -> Decimal:
        return self._used.get(symbol, Decimal("0"))

    def open_and_reserved_slots(self, symbol: str) -> int:
        return self._slots.get(symbol, 0)

    def record_open(self, symbol: str, invested_quote: Any) -> None:
        invested = _as_decimal(invested_quote)
        self._used[symbol] = self.used_capital(symbol) + invested
        self._slots[symbol] = self.open_and_reserved_slots(symbol) + 1
        self._quote -= invested

    def record_close(self, symbol: str, invested_quote: Any, net_proceeds: Any) -> None:
        self._used[symbol] = self.used_capital(symbol) - _as_decimal(invested_quote)
        self._slots[symbol] = max(0, self.open_and_reserved_slots(symbol) - 1)
        self._quote += _as_decimal(net_proceeds)

    def apply_report(self, report: TickReport) -> None:
        """Fold a tick's entries/exits into the ledger."""
        for position in report.entries:
            self.record_open(position.symbol, position.entry.invested_quote_cost)
        for position, pnl in report.exits:
            net_proceeds = pnl.gross_proceeds - pnl.exit_fees_quote
            self.record_close(position.symbol, position.entry.invested_quote_cost, net_proceeds)


class PaperExecution:
    """An ``ExecutionPort`` that simulates fills from live prices (no real orders).

    Buys fill at the best ask, sells at the best bid; if the book is empty the
    last closed candle's close is used. An optional ``fee_rate`` applies a
    quote-denominated commission to each fill (default 0 — free paper trading);
    the backtester passes a realistic rate.
    """

    def __init__(
        self,
        market_data: MarketDataPort,
        quote_asset: str = "USDT",
        fee_rate: Any = Decimal("0"),
    ) -> None:
        self._md = market_data
        self._quote_asset = quote_asset
        self._fee_rate = _as_decimal(fee_rate)

    def _reference_price(self, symbol: str, side: str) -> Decimal:
        book = self._md.get_order_book(symbol)
        if side == "BUY" and book.asks:
            return min(price for price, _ in book.asks)
        if side == "SELL" and book.bids:
            return max(price for price, _ in book.bids)
        candles = self._md.get_closed_candles(symbol, 1)
        if candles:
            return _as_decimal(candles[-1].close)
        raise LookupError(f"no reference price available for {symbol}")

    def market_buy(self, symbol: str, quote_amount: Decimal) -> list:
        price = self._reference_price(symbol, "BUY")
        qty = _as_decimal(quote_amount) / price
        commission = _as_decimal(quote_amount) * self._fee_rate
        return [Fill(price, qty, commission, self._quote_asset)]

    def market_sell(self, symbol: str, base_qty: Decimal) -> list:
        price = self._reference_price(symbol, "SELL")
        commission = price * _as_decimal(base_qty) * self._fee_rate
        return [Fill(price, _as_decimal(base_qty), commission, self._quote_asset)]
