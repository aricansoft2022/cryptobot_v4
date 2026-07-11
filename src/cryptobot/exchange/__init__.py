"""Binance adapter: symbol filters, fill aggregation, and market-data mapping.

Pure translation and exchange mechanics only — no strategy decisions and no I/O.
Live connectivity (REST/websocket, credentials) is supplied by the runtime as an
injected transport/port.
"""

from .fills import Fill, RealizedPnL, aggregate_entry, realized_pnl
from .filters import SymbolFilters
from .market_data import parse_depth, parse_klines

__all__ = [
    "SymbolFilters",
    "Fill",
    "RealizedPnL",
    "aggregate_entry",
    "realized_pnl",
    "parse_klines",
    "parse_depth",
]
